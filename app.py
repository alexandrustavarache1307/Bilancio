import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from imap_tools import MailBox
import re
import uuid
import plotly.express as px

# ==============================================================================
# 1. CONFIGURAZIONE PAGINA
# ==============================================================================
st.set_page_config(page_title="Piano Pluriennale", layout="wide", page_icon="☁️")

# Funzione per pulire le chiavi di unione (Risolve il problema del matching)
def clean_key(series):
    """Rimuove spazi extra e converte in maiuscolo per garantire il match tra Budget e Reale"""
    return series.astype(str).str.strip().str.upper()

# Mappa Mesi (Questi sono i nomi che l'App userà per cercare le colonne nel file)
MAP_MESI = {1:'Gen', 2:'Feb', 3:'Mar', 4:'Apr', 5:'Mag', 6:'Giu', 7:'Lug', 8:'Ago', 9:'Set', 10:'Ott', 11:'Nov', 12:'Dic'}

MAPPA_KEYWORD = {
    "lidl": "USCITE/PRANZO", "conad": "USCITE/PRANZO", "esselunga": "USCITE/PRANZO",
    "coop": "USCITE/PRANZO", "carrefour": "USCITE/PRANZO", "eurospin": "USCITE/PRANZO",
    "aldi": "USCITE/PRANZO", "ristorante": "USCITE/PRANZO", "pizzeria": "USCITE/PRANZO",
    "sushi": "USCITE/PRANZO", "mcdonald": "USCITE/PRANZO", "burger king": "USCITE/PRANZO",
    "bar ": "USCITE/PRANZO", "caffè": "USCITE/PRANZO", "eni": "CARBURANTE",
    "q8": "CARBURANTE", "esso": "CARBURANTE", "benzina": "CARBURANTE",
    "autostrade": "VARIE", "telepass": "VARIE", "amazon": "VARIE", "paypal": "PERSONALE",
    "netflix": "SVAGO", "spotify": "SVAGO", "dazn": "SVAGO", "disney": "SVAGO",
    "farmacia": "SALUTE", "medico": "SALUTE", "ticket": "SALUTE"
}

# ==============================================================================
# 2. CARICAMENTO DATI
# ==============================================================================
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"Errore connessione: {e}"); st.stop()

@st.cache_data(ttl=0) # TTL=0 obbliga a rileggere il file a ogni modifica
def get_categories():
    try:
        df_cat = conn.read(worksheet="2026", usecols=[0, 2], header=None)
        cat_entrate = sorted([str(x).strip() for x in df_cat.iloc[3:23, 0].dropna().unique() if str(x).strip() != ""])
        cat_uscite = sorted([str(x).strip() for x in df_cat.iloc[2:23, 1].dropna().unique() if str(x).strip() != ""])
        if "DA VERIFICARE" not in cat_entrate: cat_entrate.insert(0, "DA VERIFICARE")
        if "DA VERIFICARE" not in cat_uscite: cat_uscite.insert(0, "DA VERIFICARE")
        return cat_entrate, cat_uscite
    except: return ["DA VERIFICARE"], ["DA VERIFICARE"]

CAT_ENTRATE, CAT_USCITE = get_categories()
LISTA_TUTTE = sorted(list(set(CAT_ENTRATE + CAT_USCITE)))

@st.cache_data(ttl=0)
def get_budget_data():
    try:
        df_bud = conn.read(worksheet="DB_BUDGET", usecols=list(range(14))).fillna(0)
        
        # 1. PULIZIA HEADER: Rimuove spazi dai nomi delle colonne (es. "Gen " -> "Gen")
        df_bud.columns = df_bud.columns.astype(str).str.strip()
        
        # 2. PULIZIA CATEGORIE: Crea chiave di unione
        if "Categoria" in df_bud.columns:
            df_bud["Categoria_Match"] = clean_key(df_bud["Categoria"])
        
        # 3. PULIZIA NUMERI: Rimuove € e converte in float
        for col in df_bud.columns:
            if col not in ["Categoria", "Tipo", "Categoria_Match"]:
                # Rimuove simbolo euro, punti migliaia e converte virgola in punto
                df_bud[col] = df_bud[col].astype(str).str.replace('€','').str.replace('.','').str.replace(',','.')
                df_bud[col] = pd.to_numeric(df_bud[col], errors='coerce').fillna(0)
        return df_bud
    except: return pd.DataFrame()

# ==============================================================================
# 3. LOGICHE UTILS
# ==============================================================================
def trova_categoria_smart(descrizione, lista_cats):
    desc_lower = descrizione.lower()
    for k, v in MAPPA_KEYWORD.items():
        if k in desc_lower:
            for c in lista_cats:
                if v.lower() in c.lower(): return c
    for c in lista_cats:
        if c.lower() in desc_lower: return c
    return "DA VERIFICARE"

def scarica_spese_da_gmail():
    nuove, scartate = [], []
    if "email" not in st.secrets: return pd.DataFrame(), pd.DataFrame()
    try:
        with MailBox(st.secrets["email"]["imap_server"]).login(st.secrets["email"]["user"], st.secrets["email"]["password"]) as mailbox:
            for msg in mailbox.fetch(limit=50, reverse=True):
                if "widiba" not in msg.subject.lower() and "widiba" not in msg.text.lower(): continue
                trovato = False
                # Regex
                rx_out = [r'di\s+([\d.,]+)\s+euro.*?(?:presso|per|a)\s+(.*?)(?:\.|$)', r'prelevato\s+([\d.,]+)\s+euro.*?(?:presso)\s+(.*?)(?:\.|$)']
                rx_in = [r'di\s+([\d.,]+)\s+euro.*?(?:da|a favore)\s+(.*?)(?:\.|$)', r'ricevuto\s+([\d.,]+)\s+euro\s+da\s+(.*?)(?:\.|$)']
                body = " ".join((msg.text or msg.html).split())
                for r in rx_out:
                    m = re.search(r, body, re.IGNORECASE)
                    if m:
                        imp, desc = float(m.group(1).replace('.','').replace(',','.')), m.group(2).strip()
                        nuove.append({"Data": msg.date.strftime("%Y-%m-%d"), "Descrizione": desc, "Importo": imp, "Tipo": "Uscita", "Categoria": trova_categoria_smart(desc, CAT_USCITE), "Mese": msg.date.strftime('%b-%y'), "Firma": f"{msg.date.strftime('%Y%m%d')}-{imp}"})
                        trovato = True; break
                if not trovato:
                    for r in rx_in:
                        m = re.search(r, body, re.IGNORECASE)
                        if m:
                            imp, desc = float(m.group(1).replace('.','').replace(',','.')), m.group(2).strip()
                            nuove.append({"Data": msg.date.strftime("%Y-%m-%d"), "Descrizione": desc, "Importo": imp, "Tipo": "Entrata", "Categoria": trova_categoria_smart(desc, CAT_ENTRATE), "Mese": msg.date.strftime('%b-%y'), "Firma": f"{msg.date.strftime('%Y%m%d')}-{imp}"})
                            trovato = True; break
                if not trovato:
                    scartate.append({"Data": msg.date.strftime("%Y-%m-%d"), "Descrizione": msg.subject, "Importo": 0.0, "Tipo": "Uscita", "Categoria": "DA VERIFICARE", "Mese": msg.date.strftime('%b-%y'), "Firma": f"ERR-{uuid.uuid4().hex[:6]}"})
    except Exception as e: st.error(f"Errore mail: {e}")
    return pd.DataFrame(nuove), pd.DataFrame(scartate)

def crea_prospetto(df, idx, cols):
    if df.empty: return pd.DataFrame()
    p = df.pivot_table(index=idx, columns=cols, values='Importo', aggfunc='sum', fill_value=0)
    p["TOTALE"] = p.sum(axis=1); p = p.sort_values("TOTALE", ascending=False)
    p.loc["TOTALE"] = p.sum()
    return p

# Stili
def style_uscite(val): return f'color: {"green" if val >= 0 else "red"}; font-weight: bold'
def style_entrate(val): return f'color: {"green" if val >= 0 else "red"}; font-weight: bold'

# ==============================================================================
# 4. CARICAMENTO DB
# ==============================================================================
try:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(7)), ttl=0)
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')
    df_cloud["Importo"] = pd.to_numeric(df_cloud["Importo"], errors='coerce').fillna(0)
    if "Categoria" in df_cloud.columns:
        df_cloud["Categoria_Match"] = clean_key(df_cloud["Categoria"])
except:
    df_cloud = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

if "df_mail_found" not in st.session_state: st.session_state["df_mail_found"] = pd.DataFrame()
if "df_mail_discarded" not in st.session_state: st.session_state["df_mail_discarded"] = pd.DataFrame()
if "df_manual_entry" not in st.session_state: st.session_state["df_manual_entry"] = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

# ==============================================================================
# 5. UI PRINCIPALE - TABS
# ==============================================================================
st.title("☁️ Piano Pluriennale 2026")

tab1, tab2, tab3 = st.tabs(["📥 NUOVE & IMPORTA", "📊 REPORT & BUDGET", "🗂 STORICO & MODIFICA"])

# --- TAB 1: IMPORTAZIONE ---
with tab1:
    col_search, col_act = st.columns([1, 4])
    with col_search:
        if st.button("🔎 Cerca Mail", type="primary"):
            with st.spinner("Analisi in corso..."):
                df_m, df_s = scarica_spese_da_gmail()
                st.session_state["df_mail_found"] = df_m
                st.session_state["df_mail_discarded"] = df_s
    
    st.divider()

    if not st.session_state["df_mail_discarded"].empty:
        with st.expander(f"⚠️ {len(st.session_state['df_mail_discarded'])} Mail Scartate (Da verificare)", expanded=True):
            st.dataframe(st.session_state["df_mail_discarded"][["Data", "Descrizione"]], use_container_width=True)
            if st.button("⬇️ Recupera in Manuale"):
                st.session_state["df_manual_entry"] = pd.concat([st.session_state["df_manual_entry"], st.session_state["df_mail_discarded"]], ignore_index=True)
                st.session_state["df_mail_discarded"] = pd.DataFrame(); st.rerun()

    df_mail = st.session_state["df_mail_found"]
    if not df_mail.empty:
        firme_esistenti = df_cloud["Firma"].astype(str).tolist() if "Firma" in df_cloud.columns else []
        df_clean = df_mail[~df_mail["Firma"].astype(str).isin(firme_esistenti)]
        
        st.subheader("💰 Nuove Transazioni Identificate")
        df_mail_edit = st.data_editor(
            df_clean,
            column_config={
                "Categoria": st.column_config.SelectboxColumn(options=LISTA_TUTTE),
                "Data": st.column_config.DateColumn(format="YYYY-MM-DD")
            }, use_container_width=True
        )

    st.subheader("✍️ Inserimento Manuale")
    if st.session_state["df_manual_entry"].empty:
        st.session_state["df_manual_entry"] = pd.DataFrame([{"Data": datetime.now(), "Descrizione": "", "Importo": 0.0, "Tipo": "Uscita", "Categoria": "DA VERIFICARE"}])
    
    df_man_edit = st.data_editor(
        st.session_state["df_manual_entry"],
        num_rows="dynamic",
        column_config={
            "Categoria": st.column_config.SelectboxColumn(options=LISTA_TUTTE),
            "Tipo": st.column_config.SelectboxColumn(options=["Uscita", "Entrata"]),
            "Data": st.column_config.DateColumn(format="YYYY-MM-DD"),
            "Importo": st.column_config.NumberColumn(format="%.2f €")
        }, use_container_width=True
    )

    if st.button("💾 SALVA TUTTO NEL DATABASE", type="primary", use_container_width=True):
        da_salvare = [df_cloud.drop(columns=["Categoria_Match"], errors="ignore")]
        if not df_mail.empty: da_salvare.append(df_mail_edit)
        
        df_valid_man = df_man_edit[df_man_edit["Importo"] > 0].copy()
        if not df_valid_man.empty:
            df_valid_man["Data"] = pd.to_datetime(df_valid_man["Data"])
            df_valid_man["Mese"] = df_valid_man["Data"].dt.strftime('%b-%y')
            df_valid_man["Firma"] = [f"MAN-{uuid.uuid4().hex[:6]}" for _ in range(len(df_valid_man))]
            da_salvare.append(df_valid_man)
        
        final_df = pd.concat(da_salvare, ignore_index=True)
        final_df["Data"] = pd.to_datetime(final_df["Data"]).dt.strftime("%Y-%m-%d")
        conn.update(worksheet="DB_TRANSAZIONI", data=final_df)
        st.session_state["df_mail_found"] = pd.DataFrame()
        st.session_state["df_manual_entry"] = pd.DataFrame()
        st.balloons(); st.success("Salvataggio Completato!"); st.rerun()

# ==============================================================================
# TAB 2: DASHBOARD & BUDGET (CON DIAGNOSTICA)
# ==============================================================================
with tab2:
    df_budget = get_budget_data()
    
    # DEBUGGER: Guarda qui se non trovi i dati
    with st.expander("🕵️‍♂️ DIAGNOSTICA BUDGET (Clicca qui se vedi tutto a zero)", expanded=False):
        st.write("Colonne trovate in DB_BUDGET:", list(df_budget.columns) if not df_budget.empty else "Nessuna")
        st.write("Se i nomi non coincidono con 'Gen', 'Feb', ecc., rinominali nel file Excel.")
    
    df_ana = df_cloud.copy()
    df_ana["Anno"] = df_ana["Data"].dt.year
    df_ana["MeseNum"] = df_ana["Data"].dt.month
    
    c1, c2, c3 = st.columns(3)
    with c1: anno_sel = st.selectbox("📅 Anno", sorted(df_ana["Anno"].unique(), reverse=True) if not df_ana.empty else [2026])
    with c2: periodo_sel = st.selectbox("📊 Periodo", ["Mensile", "Annuale"])
    
    mese_sel_nome = "Gen"
    if periodo_sel == "Mensile":
        with c3: mese_sel_nome = st.selectbox("📆 Mese", list(MAP_MESI.values()), index=datetime.now().month-1)
    
    # 1. Filtro Dati Reali
    df_anno = df_ana[df_ana["Anno"] == anno_sel].copy()
    
    if periodo_sel == "Mensile":
        mese_num = [k for k,v in MAP_MESI.items() if v==mese_sel_nome][0]
        df_target = df_anno[df_anno["Data"].dt.month == mese_num]
    else:
        df_target = df_anno.copy()

    # 2. KPI Generali (Sull'anno)
    k1, k2, k3 = st.columns(3)
    ent_t = df_anno[df_anno["Tipo"]=="Entrata"]["Importo"].sum()
    usc_t = df_anno[df_anno["Tipo"]=="Uscita"]["Importo"].sum()
    k1.metric("Entrate Totali (Anno)", f"{ent_t:,.2f} €")
    k2.metric("Uscite Totali (Anno)", f"{usc_t:,.2f} €")
    k3.metric("Saldo Netto (Anno)", f"{(ent_t - usc_t):,.2f} €")
    st.divider()

    # 3. PREPARAZIONE DATI PER IL CONFRONTO (Safe Mode)
    bud_view = pd.DataFrame()
    col_found = False

    # A. Preparazione Budget
    if not df_budget.empty:
        if periodo_sel == "Mensile":
            if mese_sel_nome in df_budget.columns:
                bud_view = df_budget[["Categoria", "Categoria_Match", "Tipo", mese_sel_nome]].rename(columns={mese_sel_nome: "Budget"})
                if mese_sel_nome != "Gen": bud_view = bud_view[bud_view["Categoria"] != "SALDO INIZIALE"]
                col_found = True
        elif periodo_sel == "Annuale":
            col_mesi = [c for c in df_budget.columns if c in MAP_MESI.values()]
            if col_mesi:
                df_budget["Budget"] = df_budget[col_mesi].sum(axis=1)
                bud_view = df_budget[["Categoria", "Categoria_Match", "Tipo", "Budget"]]
                col_found = True
    
    if not col_found and periodo_sel == "Mensile":
        st.warning(f"⚠️ Colonna '{mese_sel_nome}' non trovata nel Budget. Mostro solo spese reali.")

    # B. Preparazione Consuntivo (Reale)
    if not df_target.empty:
        # Assicuriamoci che Categoria_Match esista
        if "Categoria_Match" not in df_target.columns:
             df_target["Categoria_Match"] = clean_key(df_target["Categoria"])
        
        cons = df_target.groupby(["Categoria_Match", "Tipo"])["Importo"].sum().reset_index().rename(columns={"Importo": "Reale"})
        # Se abbiamo il budget, usiamo i nomi belli del budget, altrimenti usiamo quelli del DB
        if not bud_view.empty:
            cons = pd.merge(cons, df_budget[["Categoria", "Categoria_Match"]].drop_duplicates(), on="Categoria_Match", how="left")
            cons["Categoria"] = cons["Categoria"].fillna(cons["Categoria_Match"])
        else:
            # Recupera un nome categoria decente dal target se il budget non c'è
            temp_map = df_target[["Categoria", "Categoria_Match"]].drop_duplicates().set_index("Categoria_Match")["Categoria"]
            cons["Categoria"] = cons["Categoria_Match"].map(temp_map)
    else:
        cons = pd.DataFrame(columns=["Categoria", "Categoria_Match", "Tipo", "Reale"])

    # C. MERGE (Full Outer Join per non perdere nulla)
    if not bud_view.empty:
        # Merge su Categoria_Match
        final = pd.merge(bud_view, cons[["Categoria_Match", "Reale"]], on="Categoria_Match", how="outer").fillna(0)
        # Se Categoria è NaN (c'era solo nel Reale), recuperala dal Consuntivo o metti il match
        if "Categoria" in final.columns:
             final["Categoria"] = final["Categoria"].fillna(final["Categoria_Match"])
    else:
        final = cons.copy()
        final["Budget"] = 0.0
    
    # Pulizia Finale Numeri
    final["Budget"] = pd.to_numeric(final["Budget"], errors='coerce').fillna(0)
    final["Reale"] = pd.to_numeric(final["Reale"], errors='coerce').fillna(0)
    final["Delta"] = final["Budget"] - final["Reale"]

    # 4. VISUALIZZAZIONE
    # KPI Periodo
    bp, rp = final[final["Tipo"]=="Uscita"]["Budget"].sum(), final[final["Tipo"]=="Uscita"]["Reale"].sum()
    st.metric(f"Rimanente ({periodo_sel})", f"{(bp-rp):,.2f} €", delta=f"{(bp-rp):,.2f} €")

    # Tabelle e Grafici
    cg, ct = st.columns([1, 1.5])
    
    # USCITE
    out = final[final["Tipo"]=="Uscita"].copy()
    if not out.empty:
        out["Delta"] = out["Budget"] - out["Reale"]
        with cg: 
            if out["Reale"].sum() > 0: 
                st.plotly_chart(px.pie(out, values='Reale', names='Categoria', title="Spese Reali", hole=0.4), use_container_width=True)
            elif out["Budget"].sum() > 0:
                st.plotly_chart(px.pie(out, values='Budget', names='Categoria', title="Budget Previsto", hole=0.4), use_container_width=True)
            else:
                st.info("Nessun dato da graficare.")
        with ct:
            st.markdown("### 🔴 Uscite vs Budget")
            # Mostra colonne essenziali
            cols_show = ["Categoria", "Budget", "Reale", "Delta"]
            st.dataframe(
                out[cols_show].sort_values("Budget", ascending=False)
                .style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"])
                .map(style_delta_uscite, subset=["Delta"]),
                use_container_width=True, hide_index=True
            )
    
    # ENTRATE
    st.markdown("### 🟢 Entrate vs Budget")
    inc = final[final["Tipo"]=="Entrata"].copy()
    if not inc.empty:
        inc["Delta"] = inc["Reale"] - inc["Budget"]
        st.dataframe(
            inc[["Categoria", "Budget", "Reale", "Delta"]].sort_values("Reale", ascending=False)
            .style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"])
            .map(style_delta_entrate, subset=["Delta"]),
            use_container_width=True, hide_index=True
        )

    # 5. STORICO MENSILI (Fix Error Key)
    st.divider()
    st.subheader("📅 Andamento Mensile")
    if not df_anno.empty:
        # Importante: ricalcoliamo MeseNum qui per essere sicuri
        df_anno["MeseNum"] = df_anno["Data"].dt.month
        piv = crea_prospetto(df_anno[df_anno["Tipo"]=="Uscita"], "Categoria", "MeseNum").rename(columns=MAP_MESI)
        st.dataframe(piv.style.format("{:.2f} €").background_gradient(cmap="Reds", axis=None), use_container_width=True)

    # 6. STORICO ANNUALE
    col_a1, col_a2 = st.columns(2)
    with col_a1:
        st.markdown("**Top 10 Spese**")
        if not df_anno.empty:
            st.bar_chart(df_anno[df_anno["Tipo"]=="Uscita"].groupby("Categoria")["Importo"].sum().sort_values(ascending=False).head(10), color="#ff4b4b", horizontal=True)
    with col_a2:
        st.markdown("**Trend Mensile**")
        if not df_anno.empty:
            trend = df_anno.groupby(["MeseNum", "Tipo"])["Importo"].sum().unstack().fillna(0).rename(index=MAP_MESI)
            st.bar_chart(trend, color=["#2ecc71", "#ff4b4b"])

# ==============================================================================
# TAB 3: MODIFICA STORICO
# ==============================================================================
with tab3:
    st.markdown("### 🗂 Modifica Database Completo")
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')
    # Nascondo la colonna tecnica Categoria_Match all'utente
    ed_full = st.data_editor(
        df_cloud.drop(columns=["Categoria_Match"], errors="ignore"), 
        num_rows="dynamic", height=600, use_container_width=True
    )
    
    if st.button("AGGIORNA DB COMPLETO", type="primary"):
        save_full = ed_full.copy()
        save_full["Data"] = pd.to_datetime(save_full["Data"]).dt.strftime("%Y-%m-%d")
        conn.update(worksheet="DB_TRANSAZIONI", data=save_full)
        st.success("Database aggiornato!"); st.rerun()
