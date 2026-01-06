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

# Funzione essenziale per unire Categorie scritte in modo diverso (es: "Spesa" vs "SPESA ")
def clean_key(series):
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

tab1, tab2, tab3 = st.tabs(["📥 NUOVE & IMPORTA", "📊 REPORT & BUDGET", "🗂 STORICO & MODIFICA"])

# --- TAB 1 ---
with tab1:
    col_search, col_actions = st.columns([1, 4])
    with col_search:
        if st.button("🔎 Cerca Nuove Mail", type="primary"):
            with st.spinner("Analisi mail in corso..."):
                df_m, df_s = scarica_spese_da_gmail()
                st.session_state["df_mail_found"] = df_m
                st.session_state["df_mail_discarded"] = df_s
    st.divider()
    if not st.session_state["df_mail_discarded"].empty:
        with st.expander(f"⚠️ {len(st.session_state['df_mail_discarded'])} Mail Scartate", expanded=True):
            st.dataframe(st.session_state["df_mail_discarded"][["Data", "Descrizione"]], use_container_width=True)
            if st.button("⬇️ Recupera Manualmente"):
                st.session_state["df_manual_entry"] = pd.concat([st.session_state["df_manual_entry"], st.session_state["df_mail_discarded"]], ignore_index=True)
                st.session_state["df_mail_discarded"] = pd.DataFrame(); st.rerun()
    df_mail = st.session_state["df_mail_found"]
    if not df_mail.empty:
        firme = df_cloud["Firma"].astype(str).tolist() if "Firma" in df_cloud.columns else []
        df_clean = df_mail[~df_mail["Firma"].astype(str).isin(firme)]
        st.subheader("💰 Nuove Transazioni")
        df_mail_edit = st.data_editor(df_clean, column_config={"Categoria": st.column_config.SelectboxColumn(options=LISTA_TUTTE)}, use_container_width=True)
    st.subheader("✍️ Manuale"); df_man_edit = st.data_editor(st.session_state["df_manual_entry"], num_rows="dynamic", column_config={"Categoria": st.column_config.SelectboxColumn(options=LISTA_TUTTE)}, use_container_width=True)
    if st.button("💾 SALVA TUTTO", type="primary"):
        da_salvare = [df_cloud.drop(columns=["Categoria_Match"], errors="ignore")]
        if not df_mail.empty: da_salvare.append(df_mail_edit)
        valid = df_man_edit[df_man_edit["Importo"]>0].copy()
        if not valid.empty:
            valid["Data"] = pd.to_datetime(valid["Data"]); valid["Mese"] = valid["Data"].dt.strftime('%b-%y')
            valid["Firma"] = [f"MAN-{uuid.uuid4().hex[:6]}" for _ in range(len(valid))]
            da_salvare.append(valid)
        final = pd.concat(da_salvare, ignore_index=True)
        final["Data"] = pd.to_datetime(final["Data"]).dt.strftime("%Y-%m-%d")
        conn.update(worksheet="DB_TRANSAZIONI", data=final)
        st.session_state["df_mail_found"] = pd.DataFrame(); st.session_state["df_manual_entry"] = pd.DataFrame(); st.balloons(); st.rerun()

# ==============================================================================
# TAB 2: DASHBOARD & BUDGET (CON DIAGNOSTICA)
# ==============================================================================
with tab2:
    df_budget = get_budget_data()
    
    # Filtri
    c1, c2, c3 = st.columns(3)
    with c1: anno_sel = st.selectbox("📅 Anno", sorted(df_cloud["Data"].dt.year.unique(), reverse=True) if not df_cloud.empty else [2026])
    with c2: periodo_sel = st.selectbox("📊 Periodo", ["Mensile", "Annuale"])
    mese_sel_nome = "Gen"
    if periodo_sel == "Mensile":
        with c3: mese_sel_nome = st.selectbox("📆 Mese", list(MAP_MESI.values()), index=datetime.now().month-1)
    
    # --------------------------------------------------------------------------
    # 🛑 PANNELLO DIAGNOSTICO - FONDAMENTALE PER CAPIRE PERCHÉ NON CARICA
    # --------------------------------------------------------------------------
    with st.expander("🕵️‍♂️ DIAGNOSTICA BUDGET (Apri qui se i dati sono a zero)", expanded=True):
        st.write(f"**1. Mese cercato:** '{mese_sel_nome}'")
        st.write(f"**2. Colonne trovate nel tuo file Excel:** {list(df_budget.columns)}")
        
        if mese_sel_nome in df_budget.columns:
            st.success(f"✅ La colonna '{mese_sel_nome}' ESISTE!")
            valori_mese = df_budget[mese_sel_nome].sum()
            st.info(f"Totale Budget letto per {mese_sel_nome}: {valori_mese:.2f} €. (Se è 0, controlla che nel file Excel i numeri non abbiano simboli strani o siano testo).")
            st.dataframe(df_budget[["Categoria", mese_sel_nome]].head())
        else:
            st.error(f"❌ La colonna '{mese_sel_nome}' NON ESISTE. Rinominata nel file Excel esattamente come vedi nella lista sopra (punto 2).")

    # Logica Dati
    df_anno = df_cloud[df_cloud["Data"].dt.year == anno_sel].copy()
    if periodo_sel == "Mensile":
        mese_num = [k for k,v in MAP_MESI.items() if v==mese_sel_nome][0]
        df_target = df_anno[df_anno["Data"].dt.month == mese_num]
    else: df_target = df_anno.copy()

    # KPI Generali
    k1, k2, k3 = st.columns(3)
    e_tot, u_tot = df_anno[df_anno["Tipo"]=="Entrata"]["Importo"].sum(), df_anno[df_anno["Tipo"]=="Uscita"]["Importo"].sum()
    k1.metric("Entrate Anno", f"{e_tot:,.2f} €"); k2.metric("Uscite Anno", f"{u_tot:,.2f} €"); k3.metric("Saldo", f"{(e_tot-u_tot):,.2f} €")
    st.divider()

    # PREPARAZIONE BUDGET (LEFT) E REALE (RIGHT)
    bud_view = pd.DataFrame()
    
    if not df_budget.empty:
        # Costruzione Budget
        if periodo_sel == "Mensile" and mese_sel_nome in df_budget.columns:
            bud_view = df_budget[["Categoria", "Categoria_Match", "Tipo", mese_sel_nome]].rename(columns={mese_sel_nome: "Budget"})
            if mese_sel_nome != "Gen": bud_view = bud_view[bud_view["Categoria"] != "SALDO INIZIALE"]
        elif periodo_sel == "Annuale":
            col_m = [c for c in df_budget.columns if c in MAP_MESI.values()]
            df_budget["Budget"] = df_budget[col_m].sum(axis=1)
            bud_view = df_budget[["Categoria", "Categoria_Match", "Tipo", "Budget"]]
        
        # Costruzione Reale
        if not df_target.empty:
            cons = df_target.groupby(["Categoria_Match", "Tipo"])["Importo"].sum().reset_index().rename(columns={"Importo": "Reale"})
        else: cons = pd.DataFrame(columns=["Categoria_Match", "Tipo", "Reale"])

        # MERGE BUDGET-CENTRICO (Le righe del budget vincono)
        if not bud_view.empty:
            final = pd.merge(bud_view, cons[["Categoria_Match", "Reale"]], on="Categoria_Match", how="left").fillna(0)
            final["Delta"] = final["Budget"] - final["Reale"]
            
            # KPI Periodo
            bp, rp = final[final["Tipo"]=="Uscita"]["Budget"].sum(), final[final["Tipo"]=="Uscita"]["Reale"].sum()
            st.metric(f"Rimanente {periodo_sel}", f"{(bp-rp):,.2f} €", delta=f"{(bp-rp):,.2f} €")

            # Tabelle e Grafici
            cg, ct = st.columns([1, 1.5])
            out = final[final["Tipo"]=="Uscita"].copy()
            if not out.empty:
                out["Delta"] = out["Budget"] - out["Reale"]
                with cg: 
                    if out["Reale"].sum() > 0: st.plotly_chart(px.pie(out, values='Reale', names='Categoria', hole=0.4), use_container_width=True)
                with ct:
                    st.markdown("### 🔴 Uscite vs Budget")
                    st.dataframe(out[["Categoria", "Budget", "Reale", "Delta"]].sort_values("Budget", ascending=False).style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"]).map(style_uscite, subset=["Delta"]), use_container_width=True, hide_index=True)
            
            inc = final[final["Tipo"]=="Entrata"].copy()
            if not inc.empty:
                inc["Delta"] = inc["Reale"] - inc["Budget"]
                st.markdown("### 🟢 Entrate vs Budget")
                st.dataframe(inc[["Categoria", "Budget", "Reale", "Delta"]].style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"]).map(style_entrate, subset=["Delta"]), use_container_width=True, hide_index=True)
        else:
            st.warning("Budget non disponibile per il periodo selezionato.")

    st.divider(); st.subheader("📅 Storico")
    if not df_anno.empty:
        piv = crea_prospetto(df_anno[df_anno["Tipo"]=="Uscita"], "Categoria", "MeseNum").rename(columns=MAP_MESI)
        st.dataframe(piv.style.format("{:.2f} €").background_gradient(cmap="Reds", axis=None), use_container_width=True)

with tab3:
    st.markdown("### Modifica DB"); edf = st.data_editor(df_cloud.drop(columns=["Categoria_Match"], errors="ignore"), num_rows="dynamic", use_container_width=True)
    if st.button("AGGIORNA"):
        s = edf.copy(); s["Data"] = pd.to_datetime(s["Data"]).dt.strftime("%Y-%m-%d")
        conn.update(worksheet="DB_TRANSAZIONI", data=s); st.success("OK!"); st.rerun()
