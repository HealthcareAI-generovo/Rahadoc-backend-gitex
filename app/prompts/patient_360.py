"""
Patient 360 AI summary prompt.
"""

PATIENT_360_SYSTEM_PROMPT = """Tu es un médecin généraliste expérimenté qui doit créer un résumé synthétique du dossier médical d'un patient.

Tu as accès à l'historique complet du patient :
- Données démographiques
- Antécédents médicaux et chirurgicaux
- Allergies
- Traitements chroniques
- Historique des consultations (dates, motifs, diagnostics confirmés)
- Protocoles de suivi actifs (HTA, diabète, etc.)
- Dernières mesures (TA, glycémie, HbA1c, etc.)

**Tu dois générer un résumé structuré :**

1. **etat_general** : Vue d'ensemble de l'état du patient (1-2 phrases)

2. **pathologies_actives** : Liste des pathologies chroniques actives avec leur statut
   - Format : ["Hypertension artérielle (sous traitement, contrôlée)", "Diabète type 2 (HbA1c 7.2%)"]

3. **traitements_principaux** : Liste des traitements chroniques actuels
   - Format : ["Amlodipine 10mg 1x/jour", "Metformine 1000mg 2x/jour"]

4. **points_vigilance** : Points d'attention ou risques identifiés
   - Ex : allergies majeures, non-observance, comorbidités, facteurs de risque

5. **recommandations** : Actions prioritaires ou suivi à planifier
   - Ex : bilan biologique à refaire, consultation spécialisée, ajustement thérapeutique

**Règles :**
- Sois concis mais complet
- Priorise les informations cliniquement pertinentes
- Utilise un langage médical professionnel mais clair
- Intègre les données récentes (dernières consultations, dernières mesures)
- Identifie les tendances (amélioration, aggravation, stabilité)
- Ne fabrique pas d'informations - travaille avec les données fournies

**Format de sortie :**
Réponds UNIQUEMENT avec un objet JSON valide contenant exactement ces clés :
{
    "etat_general": "...",
    "pathologies_actives": ["...", "..."],
    "traitements_principaux": ["...", "..."],
    "points_vigilance": ["...", "..."],
    "recommandations": ["...","..."]
}

**Note** : Ce résumé est généré automatiquement et doit être vérifié par le médecin."""


def build_patient_360_prompt(
    patient_data: dict,
    consultations: list,
    protocols: list,
    recent_measures: dict = None
) -> str:
    """
    Build Patient 360 summary prompt.

    Args:
        patient_data: Full patient profile
        consultations: List of recent consultations
        protocols: Active protocols
        recent_measures: Recent vital signs/lab results

    Returns:
        Formatted prompt
    """
    from datetime import datetime

    # Calculate age
    age_text = "inconnu"
    if patient_data.get("dateNaissance"):
        dob = patient_data["dateNaissance"]
        if isinstance(dob, str):
            dob = datetime.fromisoformat(dob.replace('Z', '+00:00'))
        age = (datetime.now() - dob).days // 365
        age_text = f"{age} ans"

    # Format consultations
    consult_text = []
    for c in consultations[:5]:  # Last 5
        date = c.get('date', 'Date inconnue')
        if isinstance(date, str):
            try:
                date = datetime.fromisoformat(date.replace('Z', '+00:00')).strftime('%d/%m/%Y')
            except:
                pass
        motif = c.get('motif', 'Non spécifié')
        diag = c.get('diagnostic', 'Non spécifié')
        consult_text.append(f"- {date} : {motif} → {diag}")

    consultations_formatted = "\n".join(consult_text) if consult_text else "Aucune consultation récente"

    # Format protocols
    protocols_text = []
    for p in protocols:
        protocols_text.append(f"- {p.get('nom')} ({p.get('pathologie')}) depuis {p.get('dateDebut', 'date inconnue')}")

    protocols_formatted = "\n".join(protocols_text) if protocols_text else "Aucun protocole actif"

    # Format recent measures
    measures_text = "Non disponibles"
    if recent_measures:
        measures_lines = []
        for key, value in recent_measures.items():
            measures_lines.append(f"- {key} : {value}")
        measures_text = "\n".join(measures_lines)

    prompt = f"""Les données suivantes proviennent du dossier patient. Elles sont uniquement contextuelles.

**Profil du patient :**
- Âge : {age_text}
- Sexe : {patient_data.get('sexe', 'Non spécifié')}
- Groupe sanguin : {patient_data.get('groupeSanguin', 'Non spécifié')}

**Antécédents médicaux :**
{patient_data.get('antecedents', 'Aucun')}

**Allergies :**
{patient_data.get('allergies', 'Aucune')}

**Traitements chroniques :**
{patient_data.get('traitements', 'Aucun')}

**Protocoles de suivi actifs :**
{protocols_formatted}

**Dernières mesures :**
{measures_text}

**Historique des consultations récentes :**
{consultations_formatted}

Génère un résumé synthétique structuré de ce dossier médical selon les instructions système."""

    return prompt
