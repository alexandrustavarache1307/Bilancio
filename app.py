import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from imap_tools import MailBox
import re
import uuid
import plotly.express as px

# ==============================================================================
# --- CONFIGURAZIONE PAGINA ---
# ==============================================================================
st.set_page_config(
    page_title="Piano Pluriennale 2026",
    layout="wide",
    page_icon="☁️",
    initial_sidebar_state="expanded"
)

# ==============================================================================
# --- 🧠 IL CERVELLO: MAPPA PAROLE CHIAVE -> CATEGORIE ---
# ==============================================================================
# Qui puoi aggiungere tutte le parole chiave che vuoi per l'auto-categorizzazione
MAPPA_KEYWORD = {
    "lidl": "USCITE/PRANZO", "conad": "USCITE/PRANZO", "esselunga": "USCITE/PRANZO",
    "coop": "USCITE/PRANZO", "carrefour": "USCITE/PRANZO", "eurospin": "USCITE/PRANZO",
    "aldi": "USCITE/PRANZO", "ristorante": "USCITE/PRANZO", "pizzeria": "USCITE/PRANZO",
    "sushi": "USCITE/PRANZO", "mcdonald": "USCITE/PRANZO", "burger king": "USCITE/PRANZO",
    "bar ": "USCITE/PRANZO", "caffè": "USCITE/PRANZO", "eni": "CARBURANTE",
    "q8": "CARBURANTE", "esso": "CARBURANTE", "benzina": "CARBURANTE",
    "autostrade": "VARIE", "telepass": "VARIE", "amazon": "VARIE", "paypal": "PERSONALE",
    "netflix": "SVAGO", "spotify": "SVAGO", "dazn": "SVAGO", "disney": "SVAGO"
}

# ==============================================================================
# --- CONNESSIONE E CARICAMENTO DATI ---
# ==============================================================================
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"Errore critico di connessione: {e}")
    st.stop()

@st.cache_data(ttl=60)
def get_categories():
    """Recupera le categorie validi dal foglio di configurazione 2026"""
    try:
        df_cat = conn.read(worksheet="2026", usecols=[0, 2], header=None)
        cat_entrate = sorted([str(x).strip() for x in df_cat.iloc[3:23, 0].dropna().unique() if str(x).strip() != ""])
        cat_uscite = sorted([str(x).strip() for x in df_cat.iloc[2:23, 1].dropna().unique() if str(x).strip() != ""])
        
        if "DA VERIFICARE" not in cat_entrate: cat_entrate.insert(0, "DA VERIFICARE")
        if "DA VERIFICARE" not in cat_uscite: cat_uscite.insert(0, "DA VERIFICARE")
        return cat_entrate, cat_uscite
    except Exception as e:
        st.sidebar.error(f"Errore caricamento categorie: {e}")
        return ["DA VERIFICARE"], ["DA VERIFICARE"]

@st.cache_data(ttl=60)
def get_budget_data():
    """Recupera la tabella dei preventivi dal foglio DB_BUDGET"""
    try:
        df_bud = conn.read(worksheet="DB_BUDGET", usecols=list(range(14))).fillna(0)
        return df_bud
    except Exception as e:
        st.sidebar.warning(f"Foglio DB_BUDGET non trovato o non leggibile: {e}")
        return pd.DataFrame()

CAT_ENTRATE, CAT_USCITE = get_categories()
LISTA_TUTTE_CAT = sorted(list(set(CAT_ENTRATE + CAT_USCITE)))

# ==============================================================================
# --- FUNZIONI DI SERVIZIO ---
# ==============================================================================
def trova_categoria_smart(descrizione, lista_categorie_disponibili):
    """Analizza la descrizione per suggerire la categoria corretta"""
    desc_lower = descrizione.lower()
    for parola_chiave, target_categoria in MAPPA_KEYWORD.items():
        if parola_chiave in desc_lower:
            for cat in lista_categorie_disponibili:
                if target_categoria.lower() in cat.lower():
                    return cat
    return "DA VERIFICARE"

def clean_amount(val):
    """Converte valori sporchi in float puliti"""
    try:
        if isinstance(val, str):
            return float(val.replace('.', '').replace(',', '.'))
        return float(val)
    except:
        return 0.0

# ==============================================================================
# --- MOTORE DI ASPIRAZIONE MAIL (GMAIL / WIDIBA) ---
# ==============================================================================
def scarica_spese_da_gmail():
    nuove_transazioni = []
    mail_scartate = []
    
    if "email" not in st.secrets:
        st.error("Credenziali email non trovate nei secrets!")
        return pd.DataFrame(), pd.DataFrame()

    conf = st.secrets["email"]
    
    try:
        with MailBox(conf["imap_server"]).login(conf["user"], conf["password"]) as mailbox:
            # Analizziamo le ultime 50 mail
            for msg in mailbox.fetch(limit=50, reverse=True):
                soggetto = msg.subject
                corpo = msg.text or msg.html
                corpo_clean = " ".join(corpo.split())
                
                # Filtro Widiba
                if "widiba" not in corpo_clean.lower() and "widiba" not in soggetto.lower():
                    continue

                # Pattern Regex Avanzati
                regex_uscite = [
                    r'(?:pagamento|prelievo|addebito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:presso|per|a favore di|su)\s+(.*?)(?:\.|$)',
                    r'ha\s+prelevato\s+([\d.,]+)\s+euro.*?(?:presso)\s+(.*?)(?:\.|$)'
                ]
                regex_entrate = [
                    r'(?:accredito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:per|da|a favore di)\s+(.*?)(?:\.|$)',
                    r'hai\s+ricevuto\s+([\d.,]+)\s+euro\s+da\s+(.*?)(?:\.|$)'
                ]

                trovato = False
                # Ricerca Uscite
                for rx in regex_uscite:
                    m = re.search(rx, corpo_clean, re.IGNORECASE)
                    if m:
                        importo = clean_amount(m.group(1))
                        desc = m.group(2).strip()
                        nuove_transazioni.append({
                            "Data": msg.date.strftime("%Y-%m-%d"),
                            "Descrizione": desc,
                            "Importo": importo,
                            "Tipo": "Uscita",
                            "Categoria": trova_categoria_smart(desc, CAT_USCITE),
                            "Mese": msg.date.strftime('%b-%y'),
                            "Firma": f"{msg.date.strftime('%Y%m%d')}-{importo}-{desc[:5]}"
                        })
                        trovato = True; break
                
                # Ricerca Entrate (se non è uscita)
                if not trovato:
                    for rx in regex_entrate:
                        m = re.search(rx, corpo_clean, re.IGNORECASE)
                        if m:
                            importo = clean_amount(m.group(1))
                            desc = m.group(2).strip()
                            nuove_transazioni.append({
                                "Data": msg.date.strftime("%Y-%m-%d"),
                                "Descrizione": desc,
                                "Importo": importo,
                                "Tipo": "Entrata",
                                "Categoria": trova_categoria_smart(desc, CAT_ENTRATE),
                                "Mese": msg.date.strftime('%b-%y'),
                                "Firma": f"{msg.date.strftime('%Y%m%d')}-{importo}-{desc[:5]}"
                            })
                            trovato = True; break
                
                # Se è Widiba ma non ho capito l'importo -> Scartata per correzione manuale
                if not trovato:
                    mail_scartate.append({
                        "Data": msg.date.strftime("%Y-%m-%d"),
                        "Descrizione": soggetto,
                        "Importo": 0.0,
                        "Tipo": "Uscita",
                        "Categoria": "DA VERIFICARE",
                        "Mese": msg.date.strftime('%b-%y'),
                        "Firma": f"ERR-{uuid.uuid4().hex[:6]}"
                    })
                    
    except Exception as e:
        st.error(f"Errore durante la connessione IMAP: {e}")
        
    return pd.DataFrame(nuove_transazioni), pd.DataFrame(mail_scartate)

# ==============================================================================
# --- CARICAMENTO DATABASE STORAGE ---
# ==============================================================================
try:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(7)), ttl=0)
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')
    df_cloud["Importo"] = pd.to_numeric(df_cloud["Importo"], errors='coerce').fillna(0)
except Exception as e:
    st.info("Inizializzazione nuovo database transazioni...")
    df_cloud = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

# ==============================================================================
# --- STATO DELLA SESSIONE ---
# ==============================================================================
if "df_mail_found" not in st.session_state: st.session_state["df_mail_found"] = pd.DataFrame()
if "df_mail_discarded" not in st.session_state: st.session_state["df_mail_discarded"] = pd.DataFrame()
if "df_manual_entry" not in st.session_state: 
    st.session_state["df_manual_entry"] = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

# ==============================================================================
# --- INTERFACCIA UTENTE (TABS) ---
# ==============================================================================
tab1, tab2, tab3 = st.tabs(["📥 NUOVE & IMPORTA", "📊 REPORT & BUDGET", "🗂 STORICO & MODIFICA"])

# --- TAB 1: ACQUISIZIONE DATI ---
with tab1:
    st.markdown("### 🏦 Recupero Transazioni")
    col_cmd, _ = st.columns([1, 3])
    
    if col_cmd.button("🔎 AVVIA ASPIRATUTTO WIDIBA", type="primary", use_container_width=True):
        with st.spinner("Accesso a Gmail in corso..."):
            df_m, df_s = scarica_spese_da_gmail()
            st.session_state["df_mail_found"] = df_m
            st.session_state["df_mail_discarded"] = df_s
            if not df_m.empty: st.toast(f"Trovate {len(df_m)} transazioni!", icon="✅")

    # Gestione Mail Scartate
    if not st.session_state["df_mail_discarded"].empty:
        with st.expander(f"⚠️ {len(st.session_state['df_mail_discarded'])} Mail da correggere manualmente", expanded=True):
            st.info("Queste mail sono state identificate come Widiba ma l'importo va inserito a mano.")
            st.dataframe(st.session_state["df_mail_discarded"][["Data", "Descrizione"]], use_container_width=True)
            if st.button("⬇️ RECUPERA IN MANUALE"):
                st.session_state["df_manual_entry"] = pd.concat([st.session_state["df_manual_entry"], st.session_state["df_mail_discarded"]], ignore_index=True)
                st.session_state["df_mail_discarded"] = pd.DataFrame()
                st.rerun()

    # Editor Transazioni Mail Automatiche
    df_mail = st.session_state["df_mail_found"]
    if not df_mail.empty:
        st.markdown("---")
        st.subheader("📝 Revisione automatica")
        firme_esistenti = df_cloud["Firma"].astype(str).tolist() if "Firma" in df_cloud.columns else []
        df_mail_nuove = df_mail[~df_mail["Firma"].astype(str).isin(firme_esistenti)]
        
        if df_mail_nuove.empty:
            st.success("Tutte le transazioni trovate sono già presenti nel database.")
        else:
            df_mail_edit = st.data_editor(
                df_mail_nuove,
                column_config={
                    "Categoria": st.column_config.SelectboxColumn(options=LISTA_TUTTE_CAT),
                    "Data": st.column_config.DateColumn(format="YYYY-MM-DD")
                },
                use_container_width=True,
                key="editor_mail_auto"
            )

    # Editor Inserimento Manuale
    st.markdown("---")
    st.subheader("✍️ Inserimento Manuale / Contanti")
    if st.session_state["df_manual_entry"].empty:
        st.session_state["df_manual_entry"] = pd.DataFrame([{"Data": datetime.now(), "Descrizione": "", "Importo": 0.0, "Tipo": "Uscita", "Categoria": "DA VERIFICARE"}])
    
    df_man_edit = st.data_editor(
        st.session_state["df_manual_entry"],
        num_rows="dynamic",
        column_config={
            "Categoria": st.column_config.SelectboxColumn(options=LISTA_TUTTE_CAT),
            "Tipo": st.column_config.SelectboxColumn(options=["Uscita", "Entrata"]),
            "Data": st.column_config.DateColumn(format="YYYY-MM-DD")
        },
        use_container_width=True,
        key="editor_manuale"
    )

    # Pulsante di Salvataggio Finale
    if st.button("💾 SALVA DEFINITIVAMENTE NEL CLOUD", type="primary", use_container_width=True):
        final_list = [df_cloud]
        
        # Aggiungi mail auto se presenti
        if not df_mail.empty and not df_mail_nuove.empty:
            final_list.append(df_mail_edit)
        
        # Aggiungi manuali se hanno importo > 0
        df_man_valide = df_man_edit[df_man_edit["Importo"] > 0].copy()
        if not df_man_valide.empty:
            df_man_valide["Data"] = pd.to_datetime(df_man_valide["Data"])
            df_man_valide["Mese"] = df_man_valide["Data"].dt.strftime('%b-%y')
            df_man_valide["Firma"] = [f"MAN-{uuid.uuid4().hex[:6]}" for _ in range(len(df_man_valide))]
            final_list.append(df_man_valide)
            
        if len(final_list) > 1:
            df_final = pd.concat(final_list, ignore_index=True)
            df_final["Data"] = pd.to_datetime(df_final["Data"]).dt.strftime("%Y-%m-%d")
            conn.update(worksheet="DB_TRANSAZIONI", data=df_final)
            
            # Reset
            st.session_state["df_mail_found"] = pd.DataFrame()
            st.session_state["df_manual_entry"] = pd.DataFrame()
            st.balloons()
            st.success("Tutte le operazioni sono state salvate correttamente!")
            st.rerun()

# --- TAB 2: REPORTING & CONTROLLO BUDGET ---
with tab2:
    st.markdown("### 📊 Dashboard Analitica")
    df_budget = get_budget_data()
    map_mesi = {1:'Gen', 2:'Feb', 3:'Mar', 4:'Apr', 5:'Mag', 6:'Giu', 7:'Lug', 8:'Ago', 9:'Set', 10:'Ott', 11:'Nov', 12:'Dic'}
    
    # Filtri Temporali
    c_f1, c_f2 = st.columns(2)
    with c_f1:
        anni = sorted(df_cloud["Data"].dt.year.unique(), reverse=True) if not df_cloud.empty else [2026]
        anno_sel = st.selectbox("Seleziona Anno:", anni)
    with c_f2:
        mese_sel = st.selectbox("Seleziona Mese:", list(map_mesi.values()), index=datetime.now().month-1)
    
    mese_num = [k for k,v in map_mesi.items() if v == mese_sel][0]

    # Elaborazione Dati del Mese
    df_m = df_cloud[(df_cloud["Data"].dt.month == mese_num) & (df_cloud["Data"].dt.year == anno_sel)]
    
    # 1. Calcolo Reale
    reale_u = df_m[df_m["Tipo"] == "Uscita"].groupby("Categoria")["Importo"].sum().reset_index()
    
    # 2. Calcolo Budget
    bud_u = df_budget[df_budget["Tipo"] == "Uscita"][["Categoria", mese_sel]].rename(columns={mese_sel: "Budget"})
    
    # 3. Logica Speciale SALDO INIZIALE
    if mese_sel != "Gen":
        bud_u = bud_u[bud_u["Categoria"] != "SALDO INIZIALE"]
        reale_u = reale_u[reale_u["Categoria"] != "SALDO INIZIALE"]

    # 4. Confronto
    comp = pd.merge(bud_u, reale_u, on="Categoria", how="outer").fillna(0).rename(columns={"Importo": "Reale"})
    comp["Delta"] = comp["Budget"] - comp["Reale"]

    # --- KPI: VISUALIZZAZIONE "IN TASCA" ---
    tot_bud = comp["Budget"].sum()
    tot_real = comp["Reale"].sum()
    tot_rest = tot_bud - tot_real
    
    st.divider()
    k1, k2, k3 = st.columns(3)
    k1.metric("💰 Budget Totale", f"{tot_bud:,.2f} €")
    k2.metric("💸 Speso Reale", f"{tot_real:,.2f} €")
    k3.metric("🛒 Ancora da spendere", f"{tot_rest:,.2f} €", delta=f"{tot_rest:,.2f} €", delta_color="normal")
    st.divider()

    # Alert Sforamenti
    sfori = comp[comp["Delta"] < 0]
    if not sfori.empty:
        for _, r in sfori.iterrows():
            st.error(f"⚠️ **ATTENZIONE SFORAMENTO**: Categoria **{r['Categoria']}** fuori budget di {abs(r['Delta']):.2f} €")

    # Layout Grafico + Tabella
    g_left, g_right = st.columns([1, 1.2])
    
    with g_left:
        st.markdown("#### Ripartizione Spese")
        if not reale_u.empty:
            fig = px.pie(reale_u, values='Importo', names='Categoria', hole=0.4, 
                         color_discrete_sequence=px.colors.qualitative.Safe)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Nessun dato di spesa per il periodo selezionato.")
            
    with g_right:
        st.markdown("#### Dettaglio Categorie")
        # Confronto con Stile dinamico e formattazione italiana
        st.dataframe(
            comp.sort_values("Reale", ascending=False).style.format(
                precision=2, decimal=",", thousands=".", subset=["Budget", "Reale", "Delta"]
            ).map(lambda x: 'color:red; font-weight:bold' if x < 0 else 'color:green', subset=['Delta']),
            use_container_width=True,
            hide_index=True
        )

# --- TAB 3: MANUTENZIONE DATABASE ---
with tab3:
    st.markdown("### 🗂 Gestione Storico")
    st.info("Qui puoi correggere errori passati o eliminare righe duplicate.")
    
    db_edit = st.data_editor(
        df_cloud, 
        num_rows="dynamic", 
        use_container_width=True,
        height=600,
        column_config={
            "Categoria": st.column_config.SelectboxColumn(options=LISTA_TUTTE_CAT),
            "Tipo": st.column_config.SelectboxColumn(options=["Uscita", "Entrata"]),
            "Data": st.column_config.DateColumn(format="YYYY-MM-DD")
        }
    )
    
    if st.button("🔄 APPLICA MODIFICHE AL DATABASE CLOUD", type="primary"):
        with st.spinner("Sincronizzazione in corso..."):
            df_save = db_edit.copy()
            df_save["Data"] = pd.to_datetime(df_save["Data"]).dt.strftime("%Y-%m-%d")
            conn.update(worksheet="DB_TRANSAZIONI", data=df_save)
            st.success("Database aggiornato con successo!")
            st.rerun()

# ==============================================================================
# --- FOOTER ---
# ==============================================================================
st.markdown("---")
st.caption(f"Piano Pluriennale 2026 | Database connesso: {len(df_cloud)} righe.")
