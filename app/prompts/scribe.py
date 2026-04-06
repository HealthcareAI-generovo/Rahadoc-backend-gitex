"""
MedScribe prompt for structuring consultation transcripts.
"""

MEDSCRIBE_SYSTEM_PROMPT = """Tu es un scribe médical professionnel assistant un médecin au Maroc.

Tu reçois des transcriptions de consultations médicales en français, darija ou arabe standard. Tu structures ces informations en format JSON pour le dossier patient.

Champs à extraire:
- motif: Raison de consultation ou symptôme principal (1-2 phrases)
- histoireMaladie: Chronologie des symptômes, facteurs déclenchants, évolution
- examenClinique: Observations cliniques, constantes vitales, résultats d'examen physique
- diagnostic: Diagnostic retenu ou hypothèses diagnostiques
- plan: Traitement prescrit, examens complémentaires, suivi recommandé

Consignes de rédaction:
- Rédige en français médical formel
- Utilise la terminologie médicale appropriée
- Si une information n'est pas mentionnée, laisse le champ vide
- Rapporte uniquement ce qui est explicitement dit dans la transcription
- Prends en compte le contexte patient fourni (antécédents, allergies, traitements)

Réponds uniquement avec un objet JSON valide contenant les champs ci-dessus."""


def build_medscribe_prompt(
    transcript: str,
    patient_context: dict
) -> str:
    """
    Build the user prompt for MedScribe structuring.

    Args:
        transcript: Raw consultation transcript
        patient_context: Dictionary with antecedents, allergies, traitements

    Returns:
        Formatted prompt string
    """
    context_parts = []

    if patient_context.get("antecedents"):
        context_parts.append(f"Antécédents: {patient_context['antecedents']}")

    if patient_context.get("allergies"):
        context_parts.append(f"Allergies: {patient_context['allergies']}")

    if patient_context.get("traitements"):
        context_parts.append(f"Traitements actuels: {patient_context['traitements']}")

    context_text = "\n".join(context_parts) if context_parts else "Aucun antécédent médical connu."

    prompt = f"""Contexte du patient:
{context_text}

Transcription de la consultation:
{transcript}

Analyse cette transcription et structure-la en format JSON."""

    return prompt
