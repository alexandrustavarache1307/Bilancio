import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from imap_tools import MailBox
import re
import uuid
import plotly.express as px

# ==============================================================================
# 1. CONFIGURAZIONE & HELPERS
# ==============================================================================
st.set_page_config(page_title="Piano Pluriennale", layout="wide", page_icon="☁️")

# Funzione CRUCIALE per far combaciare le categorie (toglie spazi, minuscole, ecc)
def clean_key(series):
    return series.astype(str).str.strip().str.upper()

# Mappa per tradurre i mesi (Utile per i grafici)
MAP_MESI = {1:'Gen', 2:'Feb', 3:'Mar', 4:'Apr', 5:'Mag', 6:'Giu', 7:'Lug', 8:'Ago', 9:'Set', 10:'Ott', 11:'Nov', 12:'Dic'}

MAPPA_KEYWORD = {
    "lidl": "USCITE/PRANZO", "conad": "USCITE/PRANZO", "esselunga": "USCITE/PRANZO",
    "coop": "USCITE/PRANZO", "carrefour": "USCITE/PRANZO", "eurospin": "USCITE/PRANZO",
    "aldi": "USCITE/PRANZO", "ristorante": "USCITE/PRANZO", "pizzeria": "USCITE/PRANZO",
    "sushi": "USCITE/PRANZO", "mcdonald": "USCITE/PRANZO", "burger king": "USCITE/PRANZO",
    "bar ": "USCITE/PRANZO", "caffè": "USCITE/PRANZO", "eni": "CARBURANTE",
    "q8": "CARBURANTE", "esso": "CARBURANTE", "benzina": "CARBURANTE",
    "autostrade": "VARIE", "telepass": "VARIE", "amazon": "VARIE", "paypal": "PERSONALE",
}

# ==============================================================================
# 2. CARICAMENTO DATI
# ==============================================================================
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"Errore connessione: {e}"); st.stop()

@st.cache_data(ttl=0)
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

@st.cache_data(ttl=0)
def get_budget_data():
    try:
        df_bud = conn.read(worksheet="DB_BUDGET", usecols=list(range(14))).fillna(0)
        # 1. Pulisce i nomi delle colonne
        df_bud.columns = [str(c).strip() for c in df_bud.columns]
        
        # 2. Pulisce categorie e tipo per il match
        if "Categoria" in df_bud.columns:
            df_bud["Categoria_Match"] = clean_key(df_bud["Categoria"])
        
        # 3. Converte le colonne dei mesi in numeri
        for col in df_bud.columns:
            if col not in ["Categoria", "Tipo", "Categoria_Match"]:
                df_bud[col] = df_bud[col].astype(str).str.replace('€','').str.replace('.','').str.replace(',','.')
                df_bud[col] = pd.to_numeric(df_bud[col], errors='coerce').fillna(0)
        return df_bud
    except: return pd.DataFrame()

# ==============================================================================
# 3. ELABORAZIONE E MAIL
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
# 4. CARICAMENTO DATI PRINCIPALI
# ==============================================================================
try:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(7)), ttl=0)
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')
    df_cloud["Importo"] = pd.to_numeric(df_cloud["Importo"], errors='coerce').fillna(0)
    # Pulizia categorie per il match
    if "Categoria" in df_cloud.columns: 
        df_cloud["Categoria_Match"] = clean_key(df_cloud["Categoria"])
except:
    df_cloud = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

if "df_mail_found" not in st.session_state: st.session_state["df_mail_found"] = pd.DataFrame()
if "df_mail_discarded" not in st.session_state: st.session_state["df_mail_discarded"] = pd.DataFrame()
if "df_manual_entry" not in st.session_state: st.session_state["df_manual_entry"] = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

tab1, tab2, tab3 = st.tabs(["📥 NUOVE", "📊 DASHBOARD & BUDGET", "🗂 STORICO"])

# ==============================================================================
# TAB 1: NUOVE & IMPORTA
# ==============================================================================
with tab1:
    if st.button("🔎 Cerca Mail", type="primary"):
        with st.spinner("..."): st.session_state["df_mail_found"], st.session_state["df_mail_discarded"] = scarica_spese_da_gmail()
    
    if not st.session_state["df_mail_discarded"].empty:
        with st.expander("⚠️ Mail Scartate"):
            st.dataframe(st.session_state["df_mail_discarded"])
            if st.button("Recupera Manuale"):
                st.session_state["df_manual_entry"] = pd.concat([st.session_state["df_manual_entry"], st.session_state["df_mail_discarded"]], ignore_index=True)
                st.session_state["df_mail_discarded"] = pd.DataFrame(); st.rerun()
                
    df_new = st.session_state["df_mail_found"]
    if not df_new.empty:
        firme = df_cloud["Firma"].astype(str).tolist() if "Firma" in df_cloud.columns else []
        df_new = df_new[~df_new["Firma"].astype(str).isin(firme)]
        st.subheader("Nuove Trovate"); df_edit = st.data_editor(df_new, column_config={"Categoria": st.column_config.SelectboxColumn(options=sorted(CAT_USCITE+CAT_ENTRATE))})
    
    st.subheader("Manuale"); df_man = st.data_editor(st.session_state["df_manual_entry"], num_rows="dynamic")
    
    if st.button("💾 SALVA TUTTO", type="primary"):
        save_list = [df_cloud.drop(columns=["Categoria_Match"], errors="ignore")] # Rimuovo colonna tecnica prima di salvare
        if not df_new.empty: save_list.append(df_edit)
        if not df_man[df_man["Importo"]>0].empty:
            v = df_man[df_man["Importo"]>0].copy(); v["Data"] = pd.to_datetime(v["Data"]); v["Mese"] = v["Data"].dt.strftime('%b-%y')
            v["Firma"] = [f"MAN-{uuid.uuid4().hex[:6]}" for _ in range(len(v))]
            save_list.append(v)
        final = pd.concat(save_list, ignore_index=True)
        final["Data"] = pd.to_datetime(final["Data"]).dt.strftime("%Y-%m-%d")
        conn.update(worksheet="DB_TRANSAZIONI", data=final)
        st.session_state["df_mail_found"] = pd.DataFrame(); st.session_state["df_manual_entry"] = pd.DataFrame(); st.success("Salvato!"); st.rerun()

# ==============================================================================
# TAB 2: DASHBOARD & BUDGET (CON LOGICA CORRETTA)
# ==============================================================================
with tab2:
    df_budget = get_budget_data()
    
    # Debug nascosto per controllo colonne
    with st.expander("🛠️ DEBUG DATI"):
        st.write("Colonne Budget:", list(df_budget.columns))
        if not df_budget.empty: st.write("Esempio righe Budget:", df_budget[["Categoria", "Categoria_Match"]].head())
        if not df_cloud.empty: st.write("Esempio righe Transazioni:", df_cloud[["Categoria", "Categoria_Match"]].head())

    # Filtri Temporali
    col_filter1, col_filter2, col_filter3 = st.columns(3)
    with col_filter1: 
        anno_sel = st.selectbox("📅 Anno", sorted(df_cloud["Data"].dt.year.unique(), reverse=True) if not df_cloud.empty else [2026])
    with col_filter2: 
        periodo_sel = st.selectbox("📊 Periodo", ["Mensile", "Annuale"])
    
    df_anno = df_cloud[df_cloud["Data"].dt.year == anno_sel].copy()
    
    # Logica per periodo
    mese_sel_nome = "Gen"
    if periodo_sel == "Mensile":
        with col_filter3:
            mese_sel_nome = st.selectbox("Mese", list(MAP_MESI.values()), index=datetime.now().month-1)
        mese_sel_num = [k for k,v in MAP_MESI.items() if v==mese_sel_nome][0]
        # Filtra dati reali per il mese
        df_target = df_anno[df_anno["Data"].dt.month == mese_sel_num]
    else:
        # Se annuale, prendiamo tutto
        df_target = df_anno.copy()

    # KPI Generali (Sempre sull'anno)
    k1, k2, k3 = st.columns(3)
    ent_tot = df_anno[df_anno["Tipo"]=="Entrata"]["Importo"].sum()
    usc_tot = df_anno[df_anno["Tipo"]=="Uscita"]["Importo"].sum()
    k1.metric("Entrate Anno", f"{ent_tot:,.2f} €")
    k2.metric("Uscite Anno", f"{usc_tot:,.2f} €")
    k3.metric("Saldo Anno", f"{(ent_tot - usc_tot):,.2f} €")
    st.divider()

    # LOGICA BUDGET E MERGE
    if not df_budget.empty:
        # 1. Prepara Budget in base al periodo
        if periodo_sel == "Mensile" and mese_sel_nome in df_budget.columns:
            # Prende solo la colonna del mese
            bud_periodo = df_budget[["Categoria", "Categoria_Match", "Tipo", mese_sel_nome]].rename(columns={mese_sel_nome: "Budget"})
            # Esclude Saldo Iniziale se non è Gennaio
            if mese_sel_nome != "Gen": 
                bud_periodo = bud_periodo[bud_periodo["Categoria"] != "SALDO INIZIALE"]
                df_target = df_target[df_target["Categoria"] != "SALDO INIZIALE"]
        
        elif periodo_sel == "Annuale":
            # Somma tutte le colonne che sono nei mesi (esclude Categoria, Tipo, Categoria_Match)
            cols_mesi = [c for c in df_budget.columns if c in MAP_MESI.values()]
            df_budget["Budget"] = df_budget[cols_mesi].sum(axis=1)
            bud_periodo = df_budget[["Categoria", "Categoria_Match", "Tipo", "Budget"]]
        else:
            bud_periodo = pd.DataFrame()
            st.warning(f"Colonna '{mese_sel_nome}' non trovata nel Budget.")

        # 2. Prepara Reale (Consuntivo)
        if not df_target.empty:
            # Raggruppa usando Categoria_Match per evitare duplicati "Spesa" vs "Spesa "
            consuntivo = df_target.groupby(["Categoria_Match", "Tipo"])["Importo"].sum().reset_index().rename(columns={"Importo": "Reale"})
            # Recupera il nome "bello" della categoria dal budget o dal db
            consuntivo = pd.merge(consuntivo, df_budget[["Categoria", "Categoria_Match"]].drop_duplicates(), on="Categoria_Match", how="left")
            consuntivo["Categoria"] = consuntivo["Categoria"].fillna(consuntivo["Categoria_Match"]) # Fallback
        else:
            consuntivo = pd.DataFrame(columns=["Categoria", "Categoria_Match", "Tipo", "Reale"])

        # 3. MERGE FINALE (Usa Categoria_Match come chiave!)
        if not bud_periodo.empty:
            df_final = pd.merge(bud_periodo, consuntivo[["Categoria_Match", "Reale"]], on="Categoria_Match", how="outer").fillna(0)
            
            df_final["Budget"] = pd.to_numeric(df_final["Budget"])
            df_final["Reale"] = pd.to_numeric(df_final["Reale"])
            df_final["Delta"] = df_final["Budget"] - df_final["Reale"]

            # KPI Periodo
            b_p = df_final[df_final["Tipo"]=="Uscita"]["Budget"].sum()
            r_p = df_final[df_final["Tipo"]=="Uscita"]["Reale"].sum()
            st.metric(f"Rimanente ({periodo_sel})", f"{(b_p - r_p):,.2f} €")

            # Grafici e Tabelle
            col_g, col_t = st.columns([1, 1.5])
            
            # USCITE
            out = df_final[df_final["Tipo"]=="Uscita"].copy()
            if not out.empty:
                out["Delta"] = out["Budget"] - out["Reale"]
                with col_g:
                    if out["Reale"].sum() > 0: 
                        st.plotly_chart(px.pie(out, values='Reale', names='Categoria', title="Distribuzione Uscite", hole=0.4), use_container_width=True)
                with col_t:
                    st.markdown("### 🔴 Dettaglio Uscite")
                    st.dataframe(
                        out[["Categoria", "Budget", "Reale", "Delta"]].sort_values("Reale", ascending=False)
                        .style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"])
                        .map(style_uscite, subset=["Delta"]),
                        use_container_width=True, hide_index=True
                    )

            # ENTRATE
            inc = df_final[df_final["Tipo"]=="Entrata"].copy()
            if not inc.empty:
                inc["Delta"] = inc["Reale"] - inc["Budget"]
                st.markdown("### 🟢 Dettaglio Entrate")
                st.dataframe(
                    inc[["Categoria", "Budget", "Reale", "Delta"]].sort_values("Reale", ascending=False)
                    .style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"])
                    .map(style_entrate, subset=["Delta"]),
                    use_container_width=True, hide_index=True
                )

    # --- STORICO ---
    st.divider()
    st.subheader("📅 Andamento Mensile")
    if not df_anno.empty:
        df_anno["MeseNum"] = df_anno["Data"].dt.month
        piv = crea_prospetto(df_anno[df_anno["Tipo"]=="Uscita"], "Categoria", "MeseNum").rename(columns=MAP_MESI)
        st.dataframe(piv.style.format("{:.2f} €").background_gradient(cmap="Reds", axis=None), use_container_width=True)

# ==============================================================================
# TAB 3: STORICO
# ==============================================================================
with tab3:
    st.markdown("### 🗂 Modifica Database")
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')
    ed = st.data_editor(df_cloud.drop(columns=["Categoria_Match"], errors="ignore"), num_rows="dynamic", height=600)
    if st.button("AGGIORNA DB COMPLETO"):
        sav = ed.copy(); sav["Data"] = pd.to_datetime(sav["Data"]).dt.strftime("%Y-%m-%d")
        conn.update(worksheet="DB_TRANSAZIONI", data=sav); st.success("Fatto!"); st.rerun()
