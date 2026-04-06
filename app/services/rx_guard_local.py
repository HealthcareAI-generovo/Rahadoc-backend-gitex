"""
Rx Guard local checks (Layer 1 & 2 - no AI).
Handles allergies, duplicates, and rules-based contraindications.
"""
import json
import logging
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

from app.models.rx_guard import MedicamentInput, RxGuardAlert, AlertSeverity, AlertType

logger = logging.getLogger(__name__)

# Load rules
RULES_DIR = Path(__file__).parent.parent / "rules"

with open(RULES_DIR / "interactions.json", "r", encoding="utf-8") as f:
    INTERACTIONS = json.load(f)["interactions"]

with open(RULES_DIR / "contraindications.json", "r", encoding="utf-8") as f:
    CONTRAINDICATIONS = json.load(f)


class RxGuardLocal:
    """Local (non-AI) prescription safety checks."""

    @staticmethod
    def check_allergies(
        patient_allergies: str,
        medicament: MedicamentInput
    ) -> List[RxGuardAlert]:
        """
        Layer 1: Check for known allergies.

        Args:
            patient_allergies: Patient's known allergies (text)
            medicament: Medication to check

        Returns:
            List of allergy alerts (RED severity)
        """
        alerts = []

        if not patient_allergies:
            return alerts

        # Normalize allergy text
        allergies_lower = patient_allergies.lower()

        # Check medication name and DCI
        med_name_lower = medicament.medicament.lower()
        dci_lower = (medicament.dci or "").lower()

        # Simple string matching (can be enhanced with NLP)
        for allergy_term in [med_name_lower, dci_lower]:
            if allergy_term and allergy_term in allergies_lower:
                alerts.append(RxGuardAlert(
                    severity=AlertSeverity.RED,
                    type=AlertType.ALLERGY,
                    medication=medicament.medicament,
                    description=f"ALLERGIE CONNUE : Le patient est allergique à {allergy_term}",
                    recommendation="❌ NE PAS PRESCRIRE ce médicament. Choisir une alternative non allergène.",
                    alternative=None
                ))

        # Check for class allergies (e.g., "pénicillines")
        if medicament.classe:
            classe_lower = medicament.classe.lower()
            if classe_lower in allergies_lower or any(
                keyword in allergies_lower for keyword in ["pénicilline", "céphalosporine", "sulfamide"]
            ):
                if "penicillin" in classe_lower or "beta-lactam" in classe_lower:
                    alerts.append(RxGuardAlert(
                        severity=AlertSeverity.RED,
                        type=AlertType.ALLERGY,
                        medication=medicament.medicament,
                        description=f"ALLERGIE DE CLASSE : Possible allergie croisée avec {medicament.classe}",
                        recommendation="Vérifier l'allergie croisée. En cas de doute, choisir une autre classe.",
                        alternative=None
                    ))

        return alerts

    @staticmethod
    def check_duplicates(
        current_lines: List[MedicamentInput],
        new_medicament: MedicamentInput
    ) -> List[RxGuardAlert]:
        """
        Layer 1: Check for duplicate medications (same DCI or name).

        Args:
            current_lines: Already prescribed medications
            new_medicament: New medication to add

        Returns:
            List of duplicate alerts
        """
        alerts = []

        new_dci = (new_medicament.dci or "").lower().strip()
        new_name = new_medicament.medicament.lower().strip()

        for existing in current_lines:
            existing_dci = (existing.dci or "").lower().strip()
            existing_name = existing.medicament.lower().strip()

            # Exact DCI match
            if new_dci and existing_dci and new_dci == existing_dci:
                alerts.append(RxGuardAlert(
                    severity=AlertSeverity.RED,
                    type=AlertType.DUPLICATE,
                    medication=new_medicament.medicament,
                    description=f"DOUBLON DÉTECTÉ : {existing.medicament} (même DCI: {new_dci})",
                    recommendation="❌ Éviter le doublon. Vérifier si c'est intentionnel (dosages différents).",
                    alternative=None
                ))

            # Similar name match (fuzzy)
            elif new_name and existing_name and (
                new_name == existing_name or
                new_name in existing_name or
                existing_name in new_name
            ):
                alerts.append(RxGuardAlert(
                    severity=AlertSeverity.YELLOW,
                    type=AlertType.DUPLICATE,
                    medication=new_medicament.medicament,
                    description=f"DUPLICATION POSSIBLE : {existing.medicament} déjà prescrit",
                    recommendation="⚠️ Vérifier s'il s'agit d'une duplication involontaire.",
                    alternative=None
                ))

        return alerts

    @staticmethod
    def check_contraindications(
        patient_data: Dict[str, Any],
        medicament: MedicamentInput
    ) -> List[RxGuardAlert]:
        """
        Layer 2: Check rules-based contraindications (age, pregnancy, renal, hepatic).

        Args:
            patient_data: Patient profile (age, sexe, antecedents)
            medicament: Medication to check

        Returns:
            List of contraindication alerts
        """
        alerts = []

        # Calculate patient age
        patient_age = None
        if patient_data.get("dateNaissance"):
            try:
                dob = patient_data["dateNaissance"]
                if isinstance(dob, str):
                    dob = datetime.fromisoformat(dob.replace('Z', '+00:00'))
                patient_age = (datetime.now() - dob).days // 365
            except:
                pass

        dci_lower = (medicament.dci or medicament.medicament).lower()
        classe_lower = (medicament.classe or "").lower()

        # Age restrictions
        for rule in CONTRAINDICATIONS.get("age_restrictions", []):
            rule_dci = rule["dci"].lower()
            if rule_dci in dci_lower or rule_dci == dci_lower:
                min_age = rule.get("min_age")
                max_age = rule.get("max_age")

                if patient_age is not None:
                    if min_age and patient_age < min_age:
                        severity = AlertSeverity[rule["severity"]]
                        alerts.append(RxGuardAlert(
                            severity=severity,
                            type=AlertType.CONTRAINDICATION,
                            medication=medicament.medicament,
                            description=f"CONTRE-INDICATION D'ÂGE : {rule['reason']}",
                            recommendation=rule.get("recommendation", "Ne pas prescrire à cet âge."),
                            alternative=None
                        ))

                    if max_age and patient_age > max_age:
                        severity = AlertSeverity[rule["severity"]]
                        alerts.append(RxGuardAlert(
                            severity=severity,
                            type=AlertType.CONTRAINDICATION,
                            medication=medicament.medicament,
                            description=f"PRUDENCE ÂGE > {max_age} ans : {rule['reason']}",
                            recommendation=rule.get("recommendation", "Ajuster la posologie."),
                            alternative=None
                        ))

        # Pregnancy contraindications (women 15-50 years old)
        if patient_data.get("sexe") == "FEMME" and patient_age and 15 <= patient_age <= 50:
            for rule in CONTRAINDICATIONS.get("pregnancy_contraindications", []):
                rule_dci = rule.get("dci", "").lower()
                rule_class = rule.get("class", "").lower()

                if (rule_dci and rule_dci in dci_lower) or (rule_class and rule_class in classe_lower):
                    alerts.append(RxGuardAlert(
                        severity=AlertSeverity[rule["severity"]],
                        type=AlertType.CONTRAINDICATION,
                        medication=medicament.medicament,
                        description=f"⚠️ GROSSESSE : {rule['reason']}",
                        recommendation="Vérifier le statut de grossesse. Choisir une alternative si enceinte/allaitante.",
                        alternative=None
                    ))

        # Renal/hepatic issues (check antecedents)
        antecedents_lower = (patient_data.get("antecedents") or "").lower()

        if "insuffisance rénale" in antecedents_lower or "dialyse" in antecedents_lower:
            for rule in CONTRAINDICATIONS.get("renal_adjustments", []):
                rule_dci = rule["dci"].lower()
                if rule_dci in dci_lower:
                    alerts.append(RxGuardAlert(
                        severity=AlertSeverity[rule["severity"]],
                        type=AlertType.CONTRAINDICATION,
                        medication=medicament.medicament,
                        description=f"INSUFFISANCE RÉNALE : {rule['reason']}",
                        recommendation="Ajuster la posologie ou choisir une alternative.",
                        alternative=None
                    ))

        if "insuffisance hépatique" in antecedents_lower or "cirrhose" in antecedents_lower:
            for rule in CONTRAINDICATIONS.get("hepatic_contraindications", []):
                rule_dci = rule["dci"].lower()
                if rule_dci in dci_lower:
                    alerts.append(RxGuardAlert(
                        severity=AlertSeverity[rule["severity"]],
                        type=AlertType.CONTRAINDICATION,
                        medication=medicament.medicament,
                        description=f"INSUFFISANCE HÉPATIQUE : {rule['reason']}",
                        recommendation=rule.get("max_dose_daily", "Ajuster la posologie."),
                        alternative=None
                    ))

        return alerts


# Global instance
rx_guard_local = RxGuardLocal()
