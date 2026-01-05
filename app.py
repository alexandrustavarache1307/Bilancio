import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from imap_tools import MailBox, AND
import re # Serve per cercare i prezzi nel testo

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Bilancio Cloud", layout="wide", page_icon="☁️")

# --- CONNESSIONE AL DATABASE (GOOGLE SHEETS) ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("Errore di connessione a Google Sheets. Hai configurato secrets.toml?")
    st.stop()

# --- FUNZIONE: LEGGI MAIL REALI ---
def scarica_spese_da_gmail():
    nuove_spese = []
    
    # Legge le credenziali da secrets.toml
    user = st.secrets["email"]["user"]
    pwd = st.secrets["email"]["password"]
    server = st.secrets["email"]["imap_server"]
    
    try:
        with MailBox(server).login(user, pwd) as mailbox:
            # CERCA SOLO MAIL NON LETTE (SEEN=FALSE)
            # Puoi aggiungere from_="banca@mail.it" per filtrare meglio
            for msg in mailbox.fetch(AND(seen=False), limit=5, reverse=True): 
                
                soggetto = msg.subject
                corpo = msg.text or msg.html
                
                # --- QUI SERVE LA TUA MAIL ---
                # Questa è una logica generica che cerca "€ 12,50" nel testo
                # Appena mi dai la tua mail, la rendiamo perfetta.
                match_prezzo = re.search(r'€\s?(\d+[.,]\d{2})', corpo)
                
                if match_prezzo:
                    importo_str = match_prezzo.group(1).replace('.','').replace(',','.')
                    importo = float(importo_str)
                    
                    nuove_spese.append({
                        "Data": msg.date.strftime("%Y-%m-%d"),
                        "Descrizione": soggetto[:30] + "...", # Usa l'oggetto provvisoriamente
                        "Importo": importo,
                        "Tipo": "Uscita", # Presumiamo uscita
                        "Firma": f"{msg.date}-{importo}" # Per evitare duplicati
                    })
                    
                    # OPZIONALE: Segna come letta solo se salviamo davvero
                    # mailbox.flag(msg.uid, '\\Seen', True)
                    
    except Exception as e:
        st.error(f"Errore connessione mail: {e}")
        
    return pd.DataFrame(nuove_spese)

# --- CARICAMENTO DATI ---
st.title("☁️ Dashboard Bilancio")

# Carica dati dal cloud
df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(6)), ttl=0)
# Pulisce le date
df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')

# --- BLOCCO SINCRONIZZAZIONE ---
with st.expander("🔄 Sincronizza Spese (Email)", expanded=True):
    col1, col2 = st.columns([1,3])
    
    if col1.button("📩 Cerca nelle Mail"):
        with st.spinner("Mi collego alla tua casella di posta..."):
            df_mail = scarica_spese_da_gmail()
            
        if not df_mail.empty:
            st.info(f"Trovate {len(df_mail)} possibili spese!")
            
            # FILTRO DUPLICATI (Semplificato)
            # Controlliamo se esiste già Data e Importo uguali
            df_mail["Duplicato"] = df_mail.apply(
                lambda x: ((df_cloud["Importo"] == x["Importo"]) & 
                           (df_cloud["Data"] == x["Data"])).any(), axis=1
            )
            
            df_da_salvare = df_mail[df_mail["Duplicato"] == False].copy()
            
            if not df_da_salvare.empty:
                st.write("Ecco quelle nuove (puoi modificare prima di salvare):")
                # Editor interattivo
                df_edit = st.data_editor(df_da_salvare[["Data", "Descrizione", "Importo", "Tipo"]], num_rows="dynamic")
                
                if st.button("💾 Conferma e Salva"):
                    # Calcoli automatici (Mese, Categoria)
                    df_edit["Categoria"] = "DA VERIFICARE" 
                    df_edit["Mese"] = pd.to_datetime(df_edit["Data"]).dt.strftime('%b-%y')
                    
                    # Unione
                    df_final = pd.concat([df_cloud, df_edit], ignore_index=True)
                    df_final = df_final.sort_values("Data", ascending=False)
                    
                    # Scrittura su Google
                    conn.update(worksheet="DB_TRANSAZIONI", data=df_final)
                    st.success("✅ Database aggiornato!")
                    st.rerun()
            else:
                st.warning("Tutte le mail trovate erano già nel database!")
        else:
            st.success("Nessuna nuova mail di spesa trovata.")

st.divider()

# --- ANTEPRIMA DATI ---
st.subheader("Ultime Transazioni Registrate")
st.dataframe(df_cloud.head(5))