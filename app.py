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

# --- LETTURA MAIL ---
def scarica_spese_da_gmail():
    nuove_transazioni = []
    mail_scartate = [] 
    
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

                regex_uscite = [
                    r'(?:pagamento|prelievo|addebito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:presso|per|a favore di|su)\s+(.*?)(?:\.|$)',
                    r'ha\s+prelevato\s+([\d.,]+)\s+euro.*?(?:presso)\s+(.*?)(?:\.|$)'
                ]
                regex_entrate = [
                    r'(?:accredito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:per|da|a favore di)\s+(.*?)(?:\.|$)',
                    r'hai\s+ricevuto\s+([\d.,]+)\s+euro\s+da\s+(.*?)(?:\.|$)'
                ]

                # PROVA USCITE
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

                # PROVA ENTRATE
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
                    # Mail Widiba ma non capita -> SCARTATA
                    mail_scartate.append({
                        "Data": msg.date.strftime("%Y-%m-%d"),
                        "Descrizione": soggetto, # Usiamo il soggetto come descrizione base
                        "Importo": 0.0, # Importo 0 da compilare a mano
                        "Tipo": "Uscita", # Default Uscita
                        "Categoria": "DA VERIFICARE",
                        "Mese": msg.date.strftime('%b-%y'),
                        "Firma": f"ERR-{msg.date.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
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

# Inizializza session state per le tabelle
if "df_mail_found" not in st.session_state: st.session_state["df_mail_found"] = pd.DataFrame()
if "df_mail_discarded" not in st.session_state: st.session_state["df_mail_discarded"] = pd.DataFrame()
if "df_manual_entry" not in st.session_state: st.session_state["df_manual_entry"] = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

tab1, tab2 = st.tabs(["📥 NUOVE & IMPORTA", "🗂 STORICO & MODIFICA"])

# ==========================================
# TAB 1: IMPORTAZIONE E AGGIUNTA
# ==========================================
with tab1:
    col_search, col_actions = st.columns([1, 4])
    
    with col_search:
        if st.button("🔎 Cerca Nuove Mail", type="primary"):
            with st.spinner("Analisi mail in corso..."):
                df_mail, df_scartate = scarica_spese_da_gmail()
                st.session_state["df_mail_found"] = df_mail
                st.session_state["df_mail_discarded"] = df_scartate
    
    st.divider()

    # --- 1. GESTIONE MAIL SCARTATE (RECUPERO) ---
    if not st.session_state["df_mail_discarded"].empty:
        with st.expander(f"⚠️ Ci sono {len(st.session_state['df_mail_discarded'])} mail Widiba non riconosciute", expanded=True):
            st.dataframe(st.session_state["df_mail_discarded"][["Data", "Descrizione"]], use_container_width=True, hide_index=True)
            
            if st.button("⬇️ Recupera e Correggi Manualmente"):
                # Sposta le scartate nel calderone "Manuale" per essere corrette
                recuperate = st.session_state["df_mail_discarded"].copy()
                st.session_state["df_manual_entry"] = pd.concat([st.session_state["df_manual_entry"], recuperate], ignore_index=True)
                # Svuota le scartate
                st.session_state["df_mail_discarded"] = pd.DataFrame()
                st.rerun()

    # --- 2. FILTRO DUPLICATI AUTOMATICO ---
    df_view_entrate = pd.DataFrame()
    df_view_uscite = pd.DataFrame()
    
    if not st.session_state["df_mail_found"].empty:
        df_clean = st.session_state["df_mail_found"]
        if "Firma" in df_cloud.columns:
            firme_esistenti = df_cloud["Firma"].astype(str).tolist()
            df_clean = df_clean[~df_clean["Firma"].astype(str).isin(firme_esistenti)]
        
        # FIX: Converto Data in datetime per editor
        df_clean["Data"] = pd.to_datetime(df_clean["Data"], errors='coerce')
        
        # DIVIDIAMO ENTRATE E USCITE
        df_view_entrate = df_clean[df_clean["Tipo"] == "Entrata"]
        df_view_uscite = df_clean[df_clean["Tipo"] == "Uscita"]

    # --- 3. EDITOR SEPARATI ---
    
    # ENTRATE (Verde)
    st.markdown("##### 💰 Nuove Entrate Trovate")
    if df_view_entrate.empty:
        st.info("Nessuna nuova entrata trovata.")
    else:
        edited_entrate = st.data_editor(
            df_view_entrate,
            column_config={
                "Categoria": st.column_config.SelectboxColumn(options=CAT_ENTRATE, required=True), # Solo cat entrate
                "Tipo": st.column_config.Column(disabled=True),
                "Data": st.column_config.DateColumn(format="YYYY-MM-DD", required=True),
                "Importo": st.column_config.NumberColumn(format="%.2f €")
            },
            key="edit_entrate_mail",
            use_container_width=True
        )

    # USCITE (Rosso)
    st.markdown("##### 💸 Nuove Uscite Trovate")
    if df_view_uscite.empty:
        st.info("Nessuna nuova uscita trovata.")
    else:
        edited_uscite = st.data_editor(
            df_view_uscite,
            column_config={
                "Categoria": st.column_config.SelectboxColumn(options=CAT_USCITE, required=True), # Solo cat uscite
                "Tipo": st.column_config.Column(disabled=True),
                "Data": st.column_config.DateColumn(format="YYYY-MM-DD", required=True),
                "Importo": st.column_config.NumberColumn(format="%.2f €")
            },
            key="edit_uscite_mail",
            use_container_width=True
        )

    st.markdown("---")
    
    # --- 4. INSERIMENTO MANUALE / CORREZIONI (Qui finiscono anche le scartate) ---
    st.markdown("##### ✍️ Inserimento Manuale / Correzione Scartate")
    st.caption("Aggiungi qui spese contanti o correggi le mail importate con importo 0.")
    
    # Se vuoto, aggiungi una riga vuota
    if st.session_state["df_manual_entry"].empty:
        st.session_state["df_manual_entry"] = pd.DataFrame([
            {"Data": datetime.now(), "Descrizione": "Spesa contanti", "Importo": 0.0, "Tipo": "Uscita", "Categoria": "DA VERIFICARE", "Firma": "", "Mese": ""}
        ])
    
    # Converti data
    st.session_state["df_manual_entry"]["Data"] = pd.to_datetime(st.session_state["df_manual_entry"]["Data"], errors='coerce')

    edited_manual = st.data_editor(
        st.session_state["df_manual_entry"],
        num_rows="dynamic",
        column_config={
            "Categoria": st.column_config.SelectboxColumn(options=sorted(CAT_USCITE + CAT_ENTRATE), required=True), # Qui misto perché manuale
            "Tipo": st.column_config.SelectboxColumn(options=["Uscita", "Entrata"], required=True),
            "Data": st.column_config.DateColumn(format="YYYY-MM-DD", required=True),
            "Importo": st.column_config.NumberColumn(format="%.2f €")
        },
        key="edit_manual",
        use_container_width=True
    )

    # --- 5. SALVATAGGIO UNIFICATO ---
    if st.button("💾 SALVA TUTTO NEL CLOUD", type="primary", use_container_width=True):
        da_salvare = []
        
        # Recupera Entrate Modificate (se presenti)
        if not df_view_entrate.empty:
             # Nota: Streamlit non restituisce il DF modificato direttamente se è in un if, 
             # ma 'edited_entrate' è la variabile che contiene il risultato dell'editor
             da_salvare.append(edited_entrate)
        
        # Recupera Uscite Modificate (se presenti)
        if not df_view_uscite.empty:
             da_salvare.append(edited_uscite)
             
        # Recupera Manuali (se validi, importo > 0 o descrizione cambiata)
        if not edited_manual.empty:
            # Filtriamo le righe vuote o di default se non toccate
            valid_manual = edited_manual[edited_manual["Importo"] > 0]
            if not valid_manual.empty:
                # Rigenera firme e mese per le manuali
                valid_manual["Data"] = pd.to_datetime(valid_manual["Data"])
                valid_manual["Mese"] = valid_manual["Data"].dt.strftime('%b-%y')
                valid_manual["Firma"] = valid_manual.apply(
                    lambda x: x["Firma"] if x["Firma"] and str(x["Firma"]) != "nan" else f"MAN-{x['Data'].strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}", 
                    axis=1
                )
                da_salvare.append(valid_manual)
        
        if da_salvare:
            df_new_total = pd.concat(da_salvare, ignore_index=True)
            
            # Unisci al Cloud
            df_final = pd.concat([df_cloud, df_new_total], ignore_index=True)
            df_final["Data"] = pd.to_datetime(df_final["Data"])
            df_final = df_final.sort_values("Data", ascending=False)
            df_final["Data"] = df_final["Data"].dt.strftime("%Y-%m-%d")
            
            conn.update(worksheet="DB_TRANSAZIONI", data=df_final)
            
            # Reset stato
            st.session_state["df_mail_found"] = pd.DataFrame()
            st.session_state["df_manual_entry"] = pd.DataFrame()
            st.session_state["df_mail_discarded"] = pd.DataFrame()
            
            st.balloons()
            st.success("✅ Tutto salvato correttamente!")
            st.rerun()
        else:
            st.warning("Nessun dato da salvare.")

# ==========================================
# TAB 2: MODIFICA STORICO
# ==========================================
with tab2:
    st.markdown("### 🗂 Modifica Database Completo")
    
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')

    df_storico_edited = st.data_editor(
        df_cloud,
        num_rows="dynamic",
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
    
    if st.button("🔄 AGGIORNA STORICO", type="primary"):
        df_to_update = df_storico_edited.copy()
        df_to_update["Data"] = pd.to_datetime(df_to_update["Data"]).dt.strftime("%Y-%m-%d")
        conn.update(worksheet="DB_TRANSAZIONI", data=df_to_update)
        st.success("Database aggiornato correttamnte!")
        st.rerun()
