import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from imap_tools import MailBox
import re
import uuid

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Piano Pluriennale", layout="wide", page_icon="☁️")

# --- 🧠 IL CERVELLO: MAPPA PAROLE CHIAVE ---
MAPPA_KEYWORD = {
    "lidl": "USCITE/PRANZO",
    "conad": "USCITE/PRANZO",
    "esselunga": "USCITE/PRANZO",
    "coop": "USCITE/PRANZO",
    "carrefour": "USCITE/PRANZO",
    "eurospin": "USCITE/PRANZO",
    "aldi": "USCITE/PRANZO",
    "ristorante": "USCITE/PRANZO",
    "pizzeria": "USCITE/PRANZO",
    "sushi": "USCITE/PRANZO",
    "mcdonald": "USCITE/PRANZO",
    "burger king": "USCITE/PRANZO",
    "bar ": "USCITE/PRANZO",
    "caffè": "USCITE/PRANZO",
    "eni": "CARBURANTE",
    "q8": "CARBURANTE",
    "esso": "CARBURANTE",
    "benzina": "CARBURANTE",
    "autostrade": "VARIE",
    "telepass": "VARIE",
    "amazon": "VARIE",
    "paypal": "PERSONALE",
}

# --- CONNESSIONE ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("Errore connessione. Controlla i secrets!")
    st.stop()

# --- CARICAMENTO CATEGORIE ---
@st.cache_data(ttl=60)
def get_categories():
    try:
        df_cat = conn.read(worksheet="2026", usecols=[0, 2], header=None)
        cat_entrate = df_cat.iloc[3:23, 0].dropna().unique().tolist()
        cat_uscite = df_cat.iloc[2:23, 1].dropna().unique().tolist()
        
        cat_entrate = sorted([str(x).strip() for x in cat_entrate if str(x).strip() != ""])
        cat_uscite = sorted([str(x).strip() for x in cat_uscite if str(x).strip() != ""])
        
        if "DA VERIFICARE" not in cat_entrate: cat_entrate.insert(0, "DA VERIFICARE")
        if "DA VERIFICARE" not in cat_uscite: cat_uscite.insert(0, "DA VERIFICARE")
        
        return cat_entrate, cat_uscite
    except Exception as e:
        return ["DA VERIFICARE"], ["DA VERIFICARE"]

CAT_ENTRATE, CAT_USCITE = get_categories()

# --- CERVELLO SMART ---
def trova_categoria_smart(descrizione, lista_categorie_disponibili):
    desc_lower = descrizione.lower()
    for parola_chiave, target_categoria in MAPPA_KEYWORD.items():
        if parola_chiave in desc_lower:
            for cat in lista_categorie_disponibili:
                if target_categoria.lower() in cat.lower():
                    return cat
    for cat in lista_categorie_disponibili:
        if cat.lower() in desc_lower:
            return cat
    return "DA VERIFICARE"

# --- LETTURA MAIL POTENZIATA (CON DEBUG) ---
def scarica_spese_da_gmail():
    nuove_transazioni = []
    mail_scartate = [] # Lista per il debug
    
    if "email" not in st.secrets:
        st.error("Mancano i secrets!")
        return pd.DataFrame(), pd.DataFrame()

    user = st.secrets["email"]["user"]
    pwd = st.secrets["email"]["password"]
    server = st.secrets["email"]["imap_server"]
    
    try:
        with MailBox(server).login(user, pwd) as mailbox:
            for msg in mailbox.fetch(limit=50, reverse=True): 
                
                soggetto = msg.subject
                corpo = msg.text or msg.html
                corpo_clean = " ".join(corpo.split())
                
                if "widiba" not in corpo_clean.lower() and "widiba" not in soggetto.lower():
                     continue

                importo = 0.0
                tipo = "Uscita"
                descrizione = "Transazione Generica"
                categoria_suggerita = "DA VERIFICARE"
                trovato = False

                # Regex Uscite
                regex_uscite = [
                    r'(?:pagamento|prelievo|addebito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:presso|per|a favore di|su)\s+(.*?)(?:\.|$)',
                    r'ha\s+prelevato\s+([\d.,]+)\s+euro.*?(?:presso)\s+(.*?)(?:\.|$)'
                ]
                # Regex Entrate
                regex_entrate = [
                    r'(?:accredito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:per|da|a favore di)\s+(.*?)(?:\.|$)',
                    r'hai\s+ricevuto\s+([\d.,]+)\s+euro\s+da\s+(.*?)(?:\.|$)'
                ]

                # 1. PROVA USCITE
                for rx in regex_uscite:
                    match = re.search(rx, corpo_clean, re.IGNORECASE)
                    if match:
                        importo_str = match.group(1)
                        desc_temp = match.group(2).strip() if len(match.groups()) > 1 else soggetto
                        importo = float(importo_str.replace('.', '').replace(',', '.'))
                        tipo = "Uscita"
                        descrizione = desc_temp
                        categoria_suggerita = trova_categoria_smart(descrizione, CAT_USCITE)
                        trovato = True
                        break 

                # 2. PROVA ENTRATE
                if not trovato:
                    for rx in regex_entrate:
                        match = re.search(rx, corpo_clean, re.IGNORECASE)
                        if match:
                            importo_str = match.group(1)
                            desc_temp = match.group(2).strip() if len(match.groups()) > 1 else soggetto
                            importo = float(importo_str.replace('.', '').replace(',', '.'))
                            tipo = "Entrata"
                            descrizione = desc_temp
                            categoria_suggerita = trova_categoria_smart(descrizione, CAT_ENTRATE)
                            trovato = True
                            break

                if trovato:
                    firma = f"{msg.date.strftime('%Y%m%d')}-{importo}-{descrizione[:10]}"
                    nuove_transazioni.append({
                        "Data": msg.date.strftime("%Y-%m-%d"),
                        "Descrizione": descrizione,
                        "Importo": importo,
                        "Tipo": tipo,
                        "Categoria": categoria_suggerita,
                        "Mese": msg.date.strftime('%b-%y'),
                        "Firma": firma
                    })
                else:
                    # Mail Widiba trovata ma non capita -> DEBUG
                    mail_scartate.append({
                        "Data": msg.date.strftime("%Y-%m-%d"),
                        "Soggetto": soggetto,
                        "Snippet": corpo_clean[:100] + "..."
                    })
                    
    except Exception as e:
        st.error(f"Errore lettura mail: {e}")
        
    return pd.DataFrame(nuove_transazioni), pd.DataFrame(mail_scartate)

# --- INIZIO UI ---
st.title("☁️ Piano Pluriennale 2026")

# Carica DB completo
try:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(7)), ttl=0)
except:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(6)), ttl=0)

df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')

# Struttura a TAB
tab1, tab2 = st.tabs(["📥 NUOVE & IMPORTA", "🗂 STORICO & MODIFICA"])

# ==========================================
# TAB 1: IMPORTAZIONE E AGGIUNTA
# ==========================================
with tab1:
    col_a, col_b = st.columns([1, 2])
    
    # 1. SEZIONE GMAIL
    with col_a:
        st.markdown("### 1. Da Gmail")
        if st.button("🔎 Cerca Nuove Mail", type="primary"):
            with st.spinner("Analisi mail in corso..."):
                df_mail, df_scartate = scarica_spese_da_gmail()
                
                # Salva in sessione per non perderle al refresh
                st.session_state["df_mail_found"] = df_mail
                st.session_state["df_mail_discarded"] = df_scartate

        # Visualizza Mail Scartate (Debug)
        if "df_mail_discarded" in st.session_state and not st.session_state["df_mail_discarded"].empty:
            with st.expander("⚠️ Mail Widiba ignorate (Debug)", expanded=False):
                st.warning("Queste mail contengono 'Widiba' ma lo script non ha trovato importi chiari.")
                st.dataframe(st.session_state["df_mail_discarded"], hide_index=True)

    # 2. LOGICA DI UNIONE (MAIL + MANUALE)
    with col_b:
        st.markdown("### 2. Revisione & Manuale")
        
        # Recupera mail trovate
        df_mail_view = pd.DataFrame()
        if "df_mail_found" in st.session_state and not st.session_state["df_mail_found"].empty:
            # Filtra quelle già nel DB
            if "Firma" in df_cloud.columns:
                firme_esistenti = df_cloud["Firma"].astype(str).tolist()
                df_mail_view = st.session_state["df_mail_found"][
                    ~st.session_state["df_mail_found"]["Firma"].astype(str).isin(firme_esistenti)
                ]
            else:
                df_mail_view = st.session_state["df_mail_found"]
            
            if not df_mail_view.empty:
                st.info(f"Trovate {len(df_mail_view)} nuove transazioni da Gmail.")
            else:
                st.success("Tutte le mail trovate sono già nel DB.")

        # -- TABELLA COMBINATA (MAIL + SPAZIO PER INSERIMENTO MANUALE) --
        # Creiamo un dataframe vuoto per il manuale se non esiste
        if "df_manual_entry" not in st.session_state:
            st.session_state["df_manual_entry"] = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria"])

        # Uniamo visualmente: Mail (non editabili se non categoria) + Manuali (editabili)
        # Per semplicità, usiamo un unico data_editor popolato con le mail, 
        # e con num_rows="dynamic" per aggiungerne altre a mano.
        
        # Prepariamo il DF di partenza
        df_input = df_mail_view.copy() if not df_mail_view.empty else pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])
        
        # Se vuoto, metti almeno una riga vuota d'esempio o lascia pulito
        if df_input.empty:
            df_input = pd.DataFrame([
                {"Data": datetime.now().date(), "Descrizione": "Spesa contanti", "Importo": 0.0, "Tipo": "Uscita", "Categoria": "DA VERIFICARE"}
            ])

        st.caption("Modifica le categorie suggerite o aggiungi righe manualmente in fondo.")
        
        edited_df = st.data_editor(
            df_input,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Categoria": st.column_config.SelectboxColumn(options=CAT_USCITE + CAT_ENTRATE, required=True),
                "Tipo": st.column_config.SelectboxColumn(options=["Entrata", "Uscita"], required=True),
                "Data": st.column_config.DateColumn(format="YYYY-MM-DD", required=True),
                "Importo": st.column_config.NumberColumn(format="%.2f €")
            },
            key="editor_nuovi_dati"
        )

        # SALVATAGGIO NUOVI DATI
        if st.button("💾 SALVA NUOVI DATI NEL CLOUD", type="primary", use_container_width=True):
            if not edited_df.empty:
                # Pulizia dati prima del salvataggio
                to_save = edited_df.copy()
                
                # Genera Mese e Firma se mancano (per le righe manuali)
                to_save["Data"] = pd.to_datetime(to_save["Data"])
                to_save["Mese"] = to_save["Data"].dt.strftime('%b-%y')
                
                # Funzione per generare firma se manca
                def ensure_firma(row):
                    if pd.isna(row.get("Firma")) or str(row.get("Firma")) == "nan":
                        # Firma casuale per i manuali
                        return f"MAN-{row['Data'].strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
                    return row["Firma"]
                
                to_save["Firma"] = to_save.apply(ensure_firma, axis=1)
                
                # Concatena con il DB esistente
                df_final = pd.concat([df_cloud, to_save], ignore_index=True)
                
                # Ordina e formatta
                df_final = df_final.sort_values("Data", ascending=False)
                df_final["Data"] = df_final["Data"].dt.strftime("%Y-%m-%d")
                
                # Scrivi
                conn.update(worksheet="DB_TRANSAZIONI", data=df_final)
                
                # Pulisci sessione
                st.session_state["df_mail_found"] = pd.DataFrame()
                st.toast("Dati salvati con successo!", icon="✅")
                st.balloons()
                st.rerun()

# ==========================================
# TAB 2: MODIFICA STORICO
# ==========================================
with tab2:
    st.markdown("### 🗂 Modifica Database Completo")
    st.warning("⚠️ Attenzione: le modifiche fatte qui sovrascrivono direttamente il database online.")
    
    # Editor completo
    df_storico_edited = st.data_editor(
        df_cloud,
        num_rows="dynamic", # Permette anche di cancellare o aggiungere qui
        use_container_width=True,
        height=600,
        column_config={
            "Categoria": st.column_config.SelectboxColumn(options=sorted(list(set(CAT_USCITE + CAT_ENTRATE))), required=True),
            "Tipo": st.column_config.SelectboxColumn(options=["Entrata", "Uscita"], required=True),
            "Data": st.column_config.DateColumn(format="YYYY-MM-DD", required=True),
            "Importo": st.column_config.NumberColumn(format="%.2f €")
        },
        key="editor_storico"
    )
    
    col_s1, col_s2 = st.columns([1,4])
    if col_s1.button("🔄 AGGIORNA STORICO", type="primary"):
        # Logica di salvataggio storico
        df_to_update = df_storico_edited.copy()
        df_to_update["Data"] = pd.to_datetime(df_to_update["Data"]).dt.strftime("%Y-%m-%d")
        
        conn.update(worksheet="DB_TRANSAZIONI", data=df_to_update)
        st.success("Database aggiornato correttamnte!")
        st.rerun()

st.divider()
st.caption(f"Totale righe nel DB: {len(df_cloud)}")
