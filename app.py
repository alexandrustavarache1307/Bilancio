import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from imap_tools import MailBox
import re
import uuid
import plotly.express as px

# ==============================================================================
# 1. CONFIGURAZIONE PAGINA E FUNZIONI DI UTILITÀ
# ==============================================================================
st.set_page_config(page_title="Piano Pluriennale", layout="wide", page_icon="☁️")

# Funzione per pulire le chiavi di unione (Risolve il problema del matching)
def clean_key(series):
    """Rimuove spazi extra e converte in maiuscolo per garantire il match tra Budget e Reale"""
    return series.astype(str).str.strip().str.upper()

# Mappa mesi per conversioni
MAP_MESI = {1:'Gen', 2:'Feb', 3:'Mar', 4:'Apr', 5:'Mag', 6:'Giu', 7:'Lug', 8:'Ago', 9:'Set', 10:'Ott', 11:'Nov', 12:'Dic'}

# Mappa Keyword completa
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
# 2. CONNESSIONE E CARICAMENTO DATI
# ==============================================================================
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"Errore critico di connessione: {e}")
    st.stop()

@st.cache_data(ttl=60)
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

@st.cache_data(ttl=0) # Cache disabilitata per vedere subito modifiche al file
def get_budget_data():
    try:
        df_bud = conn.read(worksheet="DB_BUDGET", usecols=list(range(14))).fillna(0)
        # 1. Pulisce i nomi delle colonne (es. "Gen " -> "Gen")
        df_bud.columns = [str(c).strip() for c in df_bud.columns]
        
        # 2. Crea colonna chiave pulita per il match
        if "Categoria" in df_bud.columns:
            df_bud["Categoria_Match"] = clean_key(df_bud["Categoria"])
        
        # 3. Converte le colonne dei mesi in numeri puri (rimuove € e formatta)
        for col in df_bud.columns:
            if col not in ["Categoria", "Tipo", "Categoria_Match"]:
                df_bud[col] = df_bud[col].astype(str).str.replace('€','').str.replace('.','').str.replace(',','.')
                df_bud[col] = pd.to_numeric(df_bud[col], errors='coerce').fillna(0)
        return df_bud
    except: return pd.DataFrame()

# ==============================================================================
# 3. LOGICA DI ELABORAZIONE
# ==============================================================================
def trova_categoria_smart(descrizione, lista_categorie_disponibili):
    desc_lower = descrizione.lower()
    # Match esatto keyword
    for parola_chiave, target_categoria in MAPPA_KEYWORD.items():
        if parola_chiave in desc_lower:
            for cat in lista_categorie_disponibili:
                if target_categoria.lower() in cat.lower(): return cat
    # Match parziale nome categoria
    for cat in lista_categorie_disponibili:
        if cat.lower() in desc_lower: return cat
    return "DA VERIFICARE"

def scarica_spese_da_gmail():
    nuove_transazioni, mail_scartate = [], []
    if "email" not in st.secrets:
        st.error("Configurazione email mancante nei secrets."); return pd.DataFrame(), pd.DataFrame()
    
    user = st.secrets["email"]["user"]
    pwd = st.secrets["email"]["password"]
    server = st.secrets["email"]["imap_server"]
    
    try:
        with MailBox(server).login(user, pwd) as mailbox:
            for msg in mailbox.fetch(limit=50, reverse=True):
                soggetto = msg.subject
                corpo_clean = " ".join((msg.text or msg.html).split())
                
                if "widiba" not in corpo_clean.lower() and "widiba" not in soggetto.lower(): continue

                importo, tipo, descrizione, trovato = 0.0, "Uscita", "Transazione Generica", False
                
                # Regex potenti
                regex_uscite = [
                    r'(?:pagamento|prelievo|addebito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:presso|per|a favore di|su)\s+(.*?)(?:\.|$)',
                    r'ha\s+prelevato\s+([\d.,]+)\s+euro.*?(?:presso)\s+(.*?)(?:\.|$)'
                ]
                regex_entrate = [
                    r'(?:accredito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:per|da|a favore di)\s+(.*?)(?:\.|$)',
                    r'hai\s+ricevuto\s+([\d.,]+)\s+euro\s+da\s+(.*?)(?:\.|$)'
                ]

                # Analisi Uscite
                for rx in regex_uscite:
                    match = re.search(rx, corpo_clean, re.IGNORECASE)
                    if match:
                        importo = float(match.group(1).replace('.', '').replace(',', '.'))
                        descrizione = match.group(2).strip()
                        tipo = "Uscita"
                        trovato = True; break 
                
                # Analisi Entrate
                if not trovato:
                    for rx in regex_entrate:
                        match = re.search(rx, corpo_clean, re.IGNORECASE)
                        if match:
                            importo = float(match.group(1).replace('.', '').replace(',', '.'))
                            descrizione = match.group(2).strip()
                            tipo = "Entrata"
                            trovato = True; break

                if trovato:
                    cat_sugg = trova_categoria_smart(descrizione, CAT_USCITE if tipo=="Uscita" else CAT_ENTRATE)
                    nuove_transazioni.append({
                        "Data": msg.date.strftime("%Y-%m-%d"),
                        "Descrizione": descrizione, "Importo": importo,
                        "Tipo": tipo, "Categoria": cat_sugg,
                        "Mese": msg.date.strftime('%b-%y'),
                        "Firma": f"{msg.date.strftime('%Y%m%d')}-{importo}-{descrizione[:10]}"
                    })
                else:
                    mail_scartate.append({
                        "Data": msg.date.strftime("%Y-%m-%d"), "Descrizione": soggetto, 
                        "Importo": 0.0, "Tipo": "Uscita", "Categoria": "DA VERIFICARE", 
                        "Mese": msg.date.strftime('%b-%y'), "Firma": f"ERR-{uuid.uuid4().hex[:6]}"
                    })
    except Exception as e: st.error(f"Errore lettura mail: {e}")
    return pd.DataFrame(nuove_transazioni), pd.DataFrame(mail_scartate)

def crea_prospetto(df, index_col, columns_col):
    if df.empty: return pd.DataFrame()
    pivot = df.pivot_table(index=index_col, columns=columns_col, values='Importo', aggfunc='sum', fill_value=0)
    pivot["TOTALE"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("TOTALE", ascending=False)
    pivot.loc["TOTALE"] = pivot.sum()
    return pivot

# Funzioni Stile Tabelle
def style_delta_uscite(val): return f'color: {"green" if val >= 0 else "red"}; font-weight: bold'
def style_delta_entrate(val): return f'color: {"green" if val >= 0 else "red"}; font-weight: bold'

# ==============================================================================
# 4. CARICAMENTO DB E SESSION STATE
# ==============================================================================
try:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(7)), ttl=0)
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')
    df_cloud["Importo"] = pd.to_numeric(df_cloud["Importo"], errors='coerce').fillna(0)
    # CREIAMO LA CHIAVE DI MATCHING ANCHE QUI
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
# TAB 2: REPORT & BUDGET
# ==============================================================================
with tab2:
    df_budget = get_budget_data()
    
    # Filtri Temporali
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1: anno_sel = st.selectbox("📅 Anno", sorted(df_cloud["Data"].dt.year.unique(), reverse=True) if not df_cloud.empty else [2026])
    with col_f2: periodo_sel = st.selectbox("📊 Periodo", ["Mensile", "Annuale"])
    
    mese_sel_nome = "Gen"
    if periodo_sel == "Mensile":
        with col_f3: mese_sel_nome = st.selectbox("📆 Mese", list(MAP_MESI.values()), index=datetime.now().month-1)
    
    # Filtraggio Dati Reali
    df_anno = df_cloud[df_cloud["Data"].dt.year == anno_sel].copy()
    
    if periodo_sel == "Mensile":
        mese_num = [k for k,v in MAP_MESI.items() if v==mese_sel_nome][0]
        df_target = df_anno[df_anno["Data"].dt.month == mese_num]
    else:
        df_target = df_anno.copy()

    # KPI Generali (Sull'anno)
    k1, k2, k3 = st.columns(3)
    ent_t = df_anno[df_anno["Tipo"]=="Entrata"]["Importo"].sum()
    usc_t = df_anno[df_anno["Tipo"]=="Uscita"]["Importo"].sum()
    k1.metric("Entrate Totali (Anno)", f"{ent_t:,.2f} €")
    k2.metric("Uscite Totali (Anno)", f"{usc_t:,.2f} €")
    k3.metric("Saldo Netto (Anno)", f"{(ent_t - usc_t):,.2f} €")
    st.divider()

    # LOGICA BUDGET & MERGE
    bud_u = pd.DataFrame()
    
    if not df_budget.empty:
        # Preparazione Budget in base al periodo
        if periodo_sel == "Mensile" and mese_sel_nome in df_budget.columns:
            bud_u = df_budget[["Categoria", "Categoria_Match", "Tipo", mese_sel_nome]].rename(columns={mese_sel_nome: "Budget"})
            if mese_sel_nome != "Gen": 
                bud_u = bud_u[bud_u["Categoria"] != "SALDO INIZIALE"]
                df_target = df_target[df_target["Categoria"] != "SALDO INIZIALE"]
        elif periodo_sel == "Annuale":
            col_mesi = [c for c in df_budget.columns if c in MAP_MESI.values()]
            df_budget["Budget"] = df_budget[col_mesi].sum(axis=1)
            bud_u = df_budget[["Categoria", "Categoria_Match", "Tipo", "Budget"]]
        
        # Preparazione Consuntivo (Raggruppamento per Categoria_Match per evitare duplicati da spazi)
        if not df_target.empty:
            reale = df_target.groupby(["Categoria_Match", "Tipo"])["Importo"].sum().reset_index().rename(columns={"Importo": "Reale"})
            # Recupera il nome originale per la visualizzazione
            reale = pd.merge(reale, df_budget[["Categoria", "Categoria_Match"]].drop_duplicates(), on="Categoria_Match", how="left")
            reale["Categoria"] = reale["Categoria"].fillna(reale["Categoria_Match"]) # Fallback se non trova il nome
        else:
            reale = pd.DataFrame(columns=["Categoria", "Categoria_Match", "Tipo", "Reale"])

        # Merge Finale
        if not bud_u.empty:
            comp = pd.merge(bud_u, reale[["Categoria_Match", "Reale"]], on="Categoria_Match", how="left").fillna(0)
            comp["Budget"] = pd.to_numeric(comp["Budget"])
            comp["Reale"] = pd.to_numeric(comp["Reale"])
            comp["Delta"] = comp["Budget"] - comp["Reale"]

            # KPI Periodo
            b_p = comp[comp["Tipo"]=="Uscita"]["Budget"].sum()
            r_p = comp[comp["Tipo"]=="Uscita"]["Reale"].sum()
            st.metric(f"Rimanente ({periodo_sel})", f"{(b_p - r_p):,.2f} €", delta=f"{(b_p - r_p):,.2f} €")

            # Grafici e Tabelle
            c_left, c_right = st.columns([1, 1.5])
            
            # Analisi Uscite
            out = comp[comp["Tipo"]=="Uscita"].copy()
            if not out.empty:
                out["Delta"] = out["Budget"] - out["Reale"]
                with c_left:
                    if out["Reale"].sum() > 0:
                        st.plotly_chart(px.pie(out, values='Reale', names='Categoria', title="Distribuzione Spese", hole=0.4), use_container_width=True)
                with c_right:
                    st.markdown("### 🔴 Dettaglio Uscite")
                    st.dataframe(
                        out[["Categoria", "Budget", "Reale", "Delta"]].sort_values("Reale", ascending=False)
                        .style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"])
                        .map(style_delta_uscite, subset=["Delta"]),
                        use_container_width=True, hide_index=True
                    )
            
            # Analisi Entrate
            st.markdown("### 🟢 Dettaglio Entrate")
            inc = comp[comp["Tipo"]=="Entrata"].copy()
            if not inc.empty:
                inc["Delta"] = inc["Reale"] - inc["Budget"]
                st.dataframe(
                    inc[["Categoria", "Budget", "Reale", "Delta"]].sort_values("Reale", ascending=False)
                    .style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"])
                    .map(style_delta_entrate, subset=["Delta"]),
                    use_container_width=True, hide_index=True
                )
        else:
            st.warning("Impossibile caricare il budget per il periodo selezionato.")

    # Storico
    st.divider()
    st.subheader("📅 Andamento Mensile")
    if not df_anno.empty:
        # QUI ERA L'ERRORE: MeseNum deve essere presente in df_anno!
        df_anno["MeseNum"] = df_anno["Data"].dt.month 
        piv = crea_prospetto(df_anno[df_anno["Tipo"]=="Uscita"], "Categoria", "MeseNum").rename(columns=MAP_MESI)
        st.dataframe(piv.style.format("{:.2f} €").background_gradient(cmap="Reds", axis=None), use_container_width=True)

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
