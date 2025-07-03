import streamlit as st
import pandas as pd
from datetime import timedelta

# ---- Session-analysis params & function ----
MARGIN       = timedelta(minutes=20)
BREAK_THRESH = timedelta(hours=8)
SHIFT_LEN    = {
    '4h':  timedelta(hours=4),
    '8h':  timedelta(hours=8),
    '12h': timedelta(hours=12)
}
SHIFT_MARGIN = timedelta(minutes=50)
MAX_SHIFT    = SHIFT_LEN['12h'] + SHIFT_MARGIN

def extract_sessions(times, events):
    sessions = []
    i, n = 0, len(times)
    while i < n:
        if events[i] != 'Wejście':
            i += 1
            continue
        t0 = times[i]
        j = i + 1
        while j < n and events[j] == 'Wejście' and times[j] - t0 <= MARGIN:
            j += 1
        k = j
        while k < n:
            if (events[k-1]=='Wyjście' and events[k]=='Wejście'
               and times[k] - times[k-1] >= BREAK_THRESH):
                break
            k += 1
        sess_times  = times[i:k]
        sess_events = events[i:k]
        t_end = next(
            (t for t,e in zip(reversed(sess_times), reversed(sess_events)) if e=='Wyjście'),
            None
        )
        breaks = sum(
            1 for a,b in zip(sess_events, sess_events[1:])
            if a=='Wyjście' and b=='Wejście'
        )
        break_durations = []
        for idx in range(len(sess_events)-1):
            if sess_events[idx]=='Wyjście' and sess_events[idx+1]=='Wejście':
                dt = sess_times[idx+1] - sess_times[idx]
                break_durations.append(dt)
        total_break_time = sum(break_durations, timedelta())
        if t_end:
            dur = t_end - t0
            if dur > MAX_SHIFT:
                assigned = 'ERROR'
            else:
                assigned = min(
                    SHIFT_LEN.items(),
                    key=lambda x: abs(x[1] - dur)
                )[0]
            sessions.append({
                'start':      t0,
                'end':        t_end,
                'duration':   dur,
                'shift':      assigned,
                'breaks':     breaks,
                'break_time': total_break_time
            })
        i = k
    return sessions

# ---- Streamlit app ----
st.set_page_config(
    page_title="Fajka tu, fajka tam",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
  .main-header {
    font-size: 2.5rem;
    font-weight: bold;
    color: #1f77b4;
    text-align: center;
    margin-bottom: 2rem;
  }
</style>
""", unsafe_allow_html=True)

@st.cache_data
def load_and_process_data(uploaded_file):
    """Read, clean, pre-filter, enrich, drop/reorder & sort."""
    # 1) Read, skip first 8 rows
    df = pd.read_excel(uploaded_file, header=8)
    # 2) Drop empty rows/cols
    df_cleaned = df.dropna(how='all').dropna(axis=1, how='all').copy()
    # 3) Pre-filter
    df_cleaned = df_cleaned[
        (df_cleaned["Urządzenie"] == "SK Kolowrót") &
        (df_cleaned["Weryfikacja"] == "karta") &
        (df_cleaned["Nazwisko"].str.strip() != "Bendkowski")
    ].copy()
    # 4) Enrich
    df_cleaned['Imię i Nazwisko'] = (
        df_cleaned['Imię'].str.strip() + " " + df_cleaned['Nazwisko'].str.strip()
    )
    df_cleaned['Data']    = pd.to_datetime(df_cleaned['Data'])
    df_cleaned['Miesiąc'] = df_cleaned['Data'].dt.month
    # 5) Drop and reorder
    df_cleaned = df_cleaned.drop(columns=[
        'Imię','Nazwisko','Urządzenie','Weryfikacja'
    ])
    df_cleaned = df_cleaned[
        ['Data','ID','Imię i Nazwisko','Zdarzenie','Miesiąc']
    ]
    # 6) Sort
    df_cleaned = df_cleaned.sort_values(
        ['Imię i Nazwisko','Data'], ascending=[True,True]
    ).reset_index(drop=True)
    return df_cleaned

def build_report(df_proc):
    """Return detailed per-shift report and monthly summary."""
    records = []
    for name, grp in df_proc.groupby('Imię i Nazwisko'):
        times  = grp['Data'].tolist()
        events = grp['Zdarzenie'].tolist()
        for sess in extract_sessions(times, events):
            bt_min = int(sess['break_time'].total_seconds() / 60)
            records.append({
                'Imię i Nazwisko':     name,
                'Start zmiany':        sess['start'],
                'Koniec zmiany':       sess['end'],
                'Przewidywana zmiana': sess['shift'],
                'Liczba przerw':       sess['breaks'],
                'Czas przerw (min)':   bt_min
            })
    report = pd.DataFrame(records)
    if report.empty:
        return report, pd.DataFrame()
    report = report.sort_values(['Imię i Nazwisko','Start zmiany'])
    report['Czas_trwania_min'] = (
        (report['Koniec zmiany'] - report['Start zmiany'])
        .dt.total_seconds()/60
    ).astype(int)
    report['Shift_month'] = report['Start zmiany'].dt.month

    podsumowanie = (
        report[report['Przewidywana zmiana'] != "ERROR"]
        .groupby(['Imię i Nazwisko','Shift_month'])
        .agg(
            dni_w_pracy=('Przewidywana zmiana','count'),
            ilosc_przerw=('Liczba przerw','sum'),
            czas_przerw_min=('Czas przerw (min)','sum'),
            sredni_czas_przerwy=('Czas przerw (min)','mean'),
        )
        .round({'sredni_czas_przerwy':2})
        .reset_index()
    )
    return report, podsumowanie

def main():
    st.markdown('<div class="main-header">📊 Fajek Session Analyzer</div>', unsafe_allow_html=True)

    # --- Sidebar only ---
with st.sidebar:
    st.header("📁 Upload & Filtry")
    uploaded_file = st.file_uploader("Excel file", type=['xlsx','xls'])
    
    if st.button("Clear All Filters"):
        st.session_state.name_filt  = 'All'
        st.session_state.month_filt = 'All'

    if uploaded_file:
        # ZMIANA: wczytaj plik tylko raz i zapisz w session_state
        if 'df_proc' not in st.session_state:
            st.session_state.df_proc = load_and_process_data(uploaded_file)
        df_proc = st.session_state.df_proc

        # ZMIANA: miesiące jako stringi
        months = ['All'] + [str(m) for m in sorted(df_proc['Miesiąc'].unique())]
        names  = ['All'] + sorted(df_proc['Imię i Nazwisko'].unique())

        # inicjalizacja filtrów
        if 'name_filt' not in st.session_state:
            st.session_state.name_filt = 'All'
        if 'month_filt' not in st.session_state:
            st.session_state.month_filt = 'All'

        # dropdowny filtrów
        st.session_state.name_filt = st.selectbox(
            "Imię i Nazwisko",
            options=names,
            index=names.index(st.session_state.name_filt)
        )
        st.session_state.month_filt = st.selectbox(
            "Miesiąc",
            options=months,
            index=months.index(st.session_state.month_filt)
        )
            
    # --- Main area: tables ---
if 'df_proc' in st.session_state:
    df_proc = st.session_state.df_proc.copy()

    # ZMIANA: przefiltruj dane przed raportem
    df_filtered = df_proc.copy()
    if st.session_state.name_filt != 'All':
        df_filtered = df_filtered[
            df_filtered['Imię i Nazwisko'] == st.session_state.name_filt
        ]
    if st.session_state.month_filt != 'All':
        df_filtered = df_filtered[
            df_filtered['Miesiąc'] == int(st.session_state.month_filt)
        ]

    # generuj raport i podsumowanie TYLKO na przefiltrowanych danych
    report, summary = build_report(df_filtered)

    # render danych źródłowych
    st.subheader("1) Dane źródłowe")
    st.dataframe(df_filtered, use_container_width=True)

    # render raportów
    st.subheader("2) Szczegółowy raport zmianowy")
    st.dataframe(report, use_container_width=True)

    st.subheader("3) Podsumowanie miesiąca")
    st.dataframe(summary, use_container_width=True)
else:
    st.write("Prześlij raport z Kołowrotka, by zacząć.")

if __name__ == "__main__":
    main()
