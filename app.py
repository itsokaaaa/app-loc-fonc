import streamlit as st
import requests
import pandas as pd
import io

# --- CONFIGURATION ---
st.set_page_config(page_title="Immo Scan v2", page_icon="🏠", layout="wide")

if "cache_dvf" not in st.session_state:
    st.session_state.cache_dvf = {}

# --- LOGIQUE MOTEUR ---


def get_location_details(query):
    """Récupère l'INSEE et gère l'exception des arrondissements de Paris."""
    url = f"https://data.geopf.fr/geocodage/search?q={query}&index=address&limit=1"
    try:
        res = requests.get(url, timeout=5).json()
        if res["features"]:
            p = res["features"][0]["properties"]
            insee = p["citycode"]
            # Fix Paris : 75056 (code ville) -> 751XX (code arrondissement)
            if insee == "75056" and p.get("postcode"):
                insee = f"751{p['postcode'][-2:]}"
            return insee, p["label"]
    except:
        pass
    return None, None


def get_rent_data(insee):
    """Interroge l'API des loyers (Ministère du Logement)."""
    rid = "55b34088-0964-415f-9df7-d87dd98a09be"
    url = f"https://tabular-api.data.gouv.fr/api/resources/{rid}/data/"
    try:
        res = requests.get(
            url, params={"INSEE_C__exact": insee, "page_size": 1}, timeout=5
        ).json()
        if res["data"]:
            return res["data"][0]
    except:
        pass
    return None


def get_sales_data(insee, kind, surface):
    """Calcule les stats d'achat via DVF avec cache départemental."""
    insee_s = str(insee).zfill(5)
    dep = insee_s[:2]

    # Gestion du Cache
    if dep not in st.session_state.cache_dvf:
        with st.spinner(f"Téléchargement des données du département {dep}..."):
            url = f"https://files.data.gouv.fr/geo-dvf/latest/csv/2024/departements/{dep}.csv.gz"
            r = requests.get(url, timeout=30)
            st.session_state.cache_dvf[dep] = pd.read_csv(
                io.BytesIO(r.content), compression="gzip", low_memory=False
            )

    df = st.session_state.cache_dvf[dep]

    # Filtrage par commune et type
    mask = (df["code_commune"].astype(str).str.zfill(5) == insee_s) & (
        df["type_local"] == kind
    )
    df_c = df[mask].copy()
    if df_c.empty:
        return None

    # Agrégation par transaction (First price / Sum surface)
    sales = df_c.groupby("id_mutation").agg(
        {"valeur_fonciere": "first", "surface_reelle_bati": "sum"}
    )
    sales = sales[sales["surface_reelle_bati"] > 5]
    sales["p_m2"] = sales["valeur_fonciere"] / sales["surface_reelle_bati"]

    # Nettoyage strict des outliers (IQR 1.0 + bornes fixes)
    sales = sales[sales["p_m2"].between(1500, 35000)]
    q1, q3 = sales["p_m2"].quantile([0.25, 0.75])
    iqr = q3 - q1
    final = sales.loc[sales["p_m2"].between(q1 - 1.0 * iqr, q3 + 1.0 * iqr), "p_m2"]

    if final.empty:
        return None
    return {
        "avg": final.mean(),
        "top": final.quantile(0.85),
        "n": len(final),
        "min": final.min(),
        "max": final.max(),
    }


# --- INTERFACE ---

st.title("🏠 Immo Scan")
st.subheader("Analyse comparative Achat / Location")

with st.sidebar:
    st.header("🔍 Recherche")
    adresse = st.text_input("Adresse ou Ville", placeholder="Paris 11, Cannes, Lyon...")
    type_bien = st.selectbox("Type de bien", ["Appartement", "Maison"])
    surface = st.number_input("Surface (m²)", min_value=1, value=35)
    st.divider()
    st.caption("Propulsé par les données ouvertes de l'État.")

if adresse:
    insee, label = get_location_details(adresse)

    if insee:
        st.info(f"📍 **Analyse pour : {label}**")

        col1, col2 = st.columns(2)

        # --- SECTION LOCATION ---
        with col1:
            st.markdown("### 📈 Marché Locatif")
            rent = get_rent_data(insee)
            if rent:
                m = rent["loypredm2"]
                st.metric("Loyer Moyen", f"{m:.2f} €/m²")
                st.write(f"**Loyer estimé : {int(m * surface)} € / mois**")
                st.caption(
                    f"Fourchette basse/haute : {rent['lwr.IPm2']:.1f} - {rent['upr.IPm2']:.1f} €/m²"
                )
            else:
                st.warning("Données locatives non trouvées pour cette zone.")

        # --- SECTION ACHAT ---
        with col2:
            st.markdown("### 💰 Marché de l'Achat")
            buy = get_sales_data(insee, type_bien, surface)
            if buy:
                st.metric("Prix Moyen", f"{int(buy['avg']):,} €/m²".replace(",", " "))
                st.write(
                    f"**Prix estimé : {int(buy['avg'] * surface):,} €**".replace(
                        ",", " "
                    )
                )
                st.write(
                    f"Prix Haut Standing : **{int(buy['top'] * surface):,} €**".replace(
                        ",", " "
                    )
                )
                st.caption(f"Analyse basée sur {buy['n']} ventes réelles (DVF 2024)")
            else:
                st.warning("Aucune donnée de vente récente disponible.")

        # --- SOURCES ---
        st.divider()
        st.markdown("### 📚 Sources des données")
        s1, s2 = st.columns(2)
        with s1:
            st.markdown(
                "[**Prix d'achat (DVF)**](https://www.data.gouv.fr/fr/datasets/demandes-de-valeurs-foncieres-geolocalisees/)  \nBase DGFiP des transactions réelles."
            )
        with s2:
            st.markdown(
                "[**Indicateurs Loyers**](https://www.data.gouv.fr/datasets/carte-des-loyers-indicateurs-de-loyers-dannonce-par-commune-en-2025)  \nEstimations du Ministère de la Transition écologique."
            )
    else:
        st.error(
            "Impossible de localiser cette adresse. Soyez plus précis (ex: 'Cannes' ou 'Paris 15')."
        )
else:
    st.write("Saisissez une adresse dans la barre latérale pour lancer l'analyse.")
