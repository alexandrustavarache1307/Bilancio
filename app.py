import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from imap_tools import MailBox
import re
import uuid
import plotly.express as px

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Piano Pluriennale", layout="wide", page_icon="☁️")

# --- MAPPA KEYWORDS ---
MAPPA_KEYWORD = {
    "lidl": "USCITE/PRANZO", "conad": "USCITE/PRANZO", "esselunga": "USCITE/PRANZO",
    "coop": "USCITE/PRANZO", "carrefour": "USCITE/PRANZO", "eurospin": "USCITE/PRANZO",
    "aldi": "USCITE/PRANZO", "ristorante": "USCITE/PRANZO", "pizzeria": "USCITE/PRANZO",
    "sushi": "USCITE/PRANZO", "mcdonald": "USCITE/PRANZO", "burger king": "USCITE/PRANZO",
    "bar ": "USCITE/PRANZO", "caffè": "USCITE/PRANZO", "eni": "CARBURANTE",
    "q8": "CARBURANTE", "esso": "CARBURANTE", "benzina": "CARBURANTE",
    "autostrade": "VARIE", "telepass": "VARIE", "amazon": "VARIE", "paypal": "PERSONALE",
}

# --- CONNESSIONE ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"Errore connessione: {e}"); st.stop()

# --- CARICAMENTO DATI ---
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
        
        # 2. Pulisce il contenuto della colonna Categoria e Tipo (Trim & Upper per matching perfetto)
        if "Categoria" in df_bud.columns:
            df_bud["Categoria"] = df_bud["Categoria"].astype(str).str.strip()
        if "Tipo" in df_bud.columns:
            df_bud["Tipo"] = df_bud["Tipo"].astype(str).str.strip()

        # 3. Forza numeri nelle colonne dei mesi
        for col in df_bud.columns:
            if col not in ["Categoria", "Tipo"]:
                # Rimuove simboli valuta se presenti e converte
                df_bud[col] = df_bud[col].astype(str).str.replace('€','').str.replace('.','').str.replace(',','.')
                df_bud[col] = pd.to_numeric(df_bud[col], errors='coerce').fillna(0)
        return df_bud
    except: return pd.DataFrame()

# --- UTILS ---
def trova_categoria_smart(descrizione, lista_cats):
    desc_lower = descrizione.lower()
    for k, v in MAPPA_KEYWORD.items():
        if k in desc_lower:
            for c in lista_cats:
                if v.lower() in c.lower(): return c
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

# --- STILI ---
def color_delta_uscite(val): return f'color: {"green" if val >= 0 else "red"}; font-weight: bold'
def color_delta_entrate(val): return f'color: {"green" if val >= 0 else "red"}; font-weight: bold'

# --- MAIN ---
try:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(7)), ttl=0)
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')
    df_cloud["Importo"] = pd.to_numeric(df_cloud["Importo"], errors='coerce').fillna(0)
    # Pulizia colonne chiave anche qui per garantire il match
    if "Categoria" in df_cloud.columns: df_cloud["Categoria"] = df_cloud["Categoria"].astype(str).str.strip()
    if "Tipo" in df_cloud.columns: df_cloud["Tipo"] = df_cloud["Tipo"].astype(str).str.strip()
except: df_cloud = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

if "df_mail_found" not in st.session_state: st.session_state["df_mail_found"] = pd.DataFrame()
if "df_mail_discarded" not in st.session_state: st.session_state["df_mail_discarded"] = pd.DataFrame()
if "df_manual_entry" not in st.session_state: st.session_state["df_manual_entry"] = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

tab1, tab2, tab3 = st.tabs(["📥 NUOVE", "📊 DASHBOARD & BUDGET", "🗂 STORICO"])

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
        save_list = [df_cloud]
        if not df_new.empty: save_list.append(df_edit)
        if not df_man[df_man["Importo"]>0].empty:
            v = df_man[df_man["Importo"]>0].copy(); v["Data"] = pd.to_datetime(v["Data"]); v["Mese"] = v["Data"].dt.strftime('%b-%y')
            v["Firma"] = [f"MAN-{uuid.uuid4().hex[:6]}" for _ in range(len(v))]
            save_list.append(v)
        final = pd.concat(save_list, ignore_index=True)
        final["Data"] = pd.to_datetime(final["Data"]).dt.strftime("%Y-%m-%d")
        conn.update(worksheet="DB_TRANSAZIONI", data=final)
        st.session_state["df_mail_found"] = pd.DataFrame(); st.session_state["df_manual_entry"] = pd.DataFrame(); st.success("Salvato!"); st.rerun()

# --- TAB 2 ---
with tab2:
    df_budget = get_budget_data()
    
    # DEBUG UTILE: Se vedi una tabella vuota, questo ti dice cosa c'è nel file
    with st.expander("🛠️ DEBUG - Dati Budget Caricati"):
        st.dataframe(df_budget.head())
    
    df_ana = df_cloud.copy()
    df_ana["Anno"] = df_ana["Data"].dt.year
    df_ana["MeseNum"] = df_ana["Data"].dt.month
    map_mesi = {1:'Gen', 2:'Feb', 3:'Mar', 4:'Apr', 5:'Mag', 6:'Giu', 7:'Lug', 8:'Ago', 9:'Set', 10:'Ott', 11:'Nov', 12:'Dic'}
    
    c1, c2 = st.columns(2)
    anno = c1.selectbox("Anno", sorted(df_ana["Anno"].unique(), reverse=True) if not df_ana.empty else [2026])
    mese_nom = c2.selectbox("Mese", list(map_mesi.values()), index=datetime.now().month-1)
    mese_num = [k for k,v in map_mesi.items() if v==mese_nom][0]

    df_anno = df_ana[df_ana["Anno"] == anno]
    
    ent, usc = df_anno[df_anno["Tipo"]=="Entrata"]["Importo"].sum(), df_anno[df_anno["Tipo"]=="Uscita"]["Importo"].sum()
    k1, k2, k3 = st.columns(3)
    k1.metric("Entrate Anno", f"{ent:,.2f} €"); k2.metric("Uscite Anno", f"{usc:,.2f} €"); k3.metric("Saldo", f"{(ent-usc):,.2f} €")
    st.divider()

    # LOGICA BUDGET - FIX MATCHING
    if not df_budget.empty and mese_nom in df_budget.columns:
        # Prepara Budget
        bud = df_budget[["Categoria", "Tipo", mese_nom]].rename(columns={mese_nom: "Budget"})
        if mese_nom != "Gen": bud = bud[bud["Categoria"] != "SALDO INIZIALE"]
        
        # Prepara Reale
        real = df_anno[(df_anno["MeseNum"]==mese_num)].groupby(["Categoria","Tipo"])["Importo"].sum().reset_index().rename(columns={"Importo":"Reale"})
        if mese_nom != "Gen": real = real[real["Categoria"] != "SALDO INIZIALE"]

        # Merge - Qui avviene la magia: on=["Categoria", "Tipo"] deve combaciare perfettamente
        comp = pd.merge(bud, real, on=["Categoria","Tipo"], how="outer").fillna(0)
        
        # Pulizia post-merge
        comp["Budget"] = pd.to_numeric(comp["Budget"], errors='coerce').fillna(0)
        comp["Reale"] = pd.to_numeric(comp["Reale"], errors='coerce').fillna(0)
        comp["Delta"] = comp["Budget"] - comp["Reale"]

        b_m, r_m = comp[comp["Tipo"]=="Uscita"]["Budget"].sum(), comp[comp["Tipo"]=="Uscita"]["Reale"].sum()
        st.metric(f"In Tasca ({mese_nom})", f"{(b_m - r_m):,.2f} €")

        c_g, c_t = st.columns([1, 1.5])
        out = comp[comp["Tipo"]=="Uscita"].copy()
        if not out.empty:
            out["Delta"] = out["Budget"] - out["Reale"]
            with c_g: 
                if out["Reale"].sum() > 0: st.plotly_chart(px.pie(out, values='Reale', names='Categoria', hole=0.4), use_container_width=True)
            with c_t:
                st.dataframe(
                    out.style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"])
                    .map(color_delta_uscite, subset=["Delta"]),
                    use_container_width=True, hide_index=True
                )
            
        st.markdown("### 🟢 Entrate vs Budget")
        inc = comp[comp["Tipo"]=="Entrata"].copy()
        inc["Delta"] = inc["Reale"] - inc["Budget"]
        st.dataframe(
            inc.style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"])
            .map(color_delta_entrate, subset=["Delta"]),
            use_container_width=True, hide_index=True
        )

    else:
        st.warning(f"Colonna '{mese_nom}' non trovata in DB_BUDGET.")
