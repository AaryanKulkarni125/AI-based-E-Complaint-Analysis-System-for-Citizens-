"""AI categorization and priority classification service for civic grievances.

Uses scikit-learn TF-IDF Vectorizer + Multinomial Naive Bayes trained on labeled
civic complaint descriptions across municipal departments, plus rule-based priority
classification and confidence scoring.
"""

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Minimum confidence required to accept AI prediction without flagging for review
CONFIDENCE_THRESHOLD = 0.60

# Realistic labeled training data across civic departments
TRAINING_DATA = [
    # Roads & Infrastructure
    ("Dangerous deep pothole on main road causing vehicle damage and bike accidents", "Roads & Infrastructure"),
    ("Broken road surface and large craters after heavy rain near market", "Roads & Infrastructure"),
    ("Footpath slabs broken and missing making it hazardous for pedestrians", "Roads & Infrastructure"),
    ("Road divider broken and concrete scattered across highway", "Roads & Infrastructure"),
    ("Asphalt washed away on arterial road, severe potholes and uneven surface", "Roads & Infrastructure"),
    ("Speed breaker damaged and loose stones causing skidding of two wheelers", "Roads & Infrastructure"),
    ("Road cave-in near subway entrance, dangerous trench exposed", "Roads & Infrastructure"),

    # Sanitation & Waste Management
    ("Garbage dump overflowing on street corner with foul smell and flies", "Sanitation & Waste Management"),
    ("Uncollected municipal trash heap attracting stray dogs and cattle", "Sanitation & Waste Management"),
    ("Dead stray dog lying on roadside for two days needs immediate removal", "Sanitation & Waste Management"),
    ("Waste collection truck has not visited our locality for the past five days", "Sanitation & Waste Management"),
    ("Public dustbins broken and waste scattered everywhere across the park", "Sanitation & Waste Management"),
    ("Illegal dumping of construction debris and debris on vacant plot", "Sanitation & Waste Management"),
    ("Litter and plastic waste blocking residential lane and entrance", "Sanitation & Waste Management"),

    # Water Supply
    ("Main drinking water pipeline burst with huge water wastage on street", "Water Supply"),
    ("No water supply in colony for the last 3 days, residents facing crisis", "Water Supply"),
    ("Contaminated dirty brown tap water with foul odor unfit for drinking", "Water Supply"),
    ("Low water pressure in municipal pipeline unable to fill overhead tanks", "Water Supply"),
    ("Underground water pipe leaking continuously flooding the lane", "Water Supply"),
    ("Water tanker requested but not delivered in drought affected area", "Water Supply"),
    ("Severely discolored water coming with mud and worms from municipal tap", "Water Supply"),

    # Drainage & Sewerage
    ("Underground sewer line blocked and overflowing dirty black water onto road", "Drainage & Sewerage"),
    ("Open manhole cover missing on busy street, extreme hazard for pedestrians", "Drainage & Sewerage"),
    ("Stormwater drain completely choked with silt and sewage water backing up", "Drainage & Sewerage"),
    ("Foul sewage water flooding into house basements and ground floors", "Drainage & Sewerage"),
    ("Gutter overflow after rainfall creating stagnant puddle and stench", "Drainage & Sewerage"),
    ("Blocked drainage culvert causing waterlogging across the entire junction", "Drainage & Sewerage"),

    # Electricity & Street Lighting
    ("Streetlight not working, entire street is pitch dark and unsafe at night", "Electricity & Street Lighting"),
    ("Electric transformer sparking violently with smoke near residential apartments", "Electricity & Street Lighting"),
    ("High voltage power lines dangling dangerously close to road and trees", "Electricity & Street Lighting"),
    ("Street lamp pole rusted and leaning dangerously, risk of falling", "Electricity & Street Lighting"),
    ("Frequent voltage fluctuations damaging household appliances", "Electricity & Street Lighting"),
    ("Underground power cable damaged during digging causing complete blackout", "Electricity & Street Lighting"),

    # Public Health
    ("Stagnant water pond breeding thousands of mosquitoes, risk of dengue malaria", "Public Health"),
    ("Severe stray dog menace with aggressive packs chasing residents and children", "Public Health"),
    ("Pest infestation and foul stench from open canal spreading disease in locality", "Public Health"),
    ("Public toilet unhygienic, no running water, severe biological hazard", "Public Health"),
    ("Chemical smoke and toxic burning of waste causing breathing difficulties", "Public Health"),
    ("Food stall operating without sanitation license in unhygienic conditions", "Public Health"),

    # General Administration
    ("Administrative delay in issuing birth certificate despite submitting all documents", "General Administration"),
    ("Municipal ward office staff demanding bribe and misbehaving with citizens", "General Administration"),
    ("Property tax assessment incorrect and discrepancy in online receipt", "General Administration"),
    ("Information kiosk at civic center out of order and no staff to assist", "General Administration"),
    ("Trade license renewal application pending without reason for over 3 months", "General Administration"),
    ("Request for information regarding municipal development plan not answered", "General Administration"),
]

# Keywords indicating High urgency / hazard
HIGH_PRIORITY_KEYWORDS = [
    "spark", "sparking", "burst", "bursting", "cave-in", "collapse", "dangling", "live wire",
    "open manhole", "manhole missing", "flooding", "blackout", "toxic", "poisonous", "fire",
    "dengue", "malaria", "emergency", "hazardous", "hazard", "dangerous", "accident",
    "hospital", "school", "fatal", "deep pothole", "explosion"
]

# Keywords indicating Low priority
LOW_PRIORITY_KEYWORDS = [
    "inquiry", "enquiry", "information", "suggestion", "request for", "schedule",
    "routine", "tree pruning", "painting", "signboard", "kiosk", "feedback"
]

_classifier_model = None
_vectorizer = None


def get_model():
    """Lazy initialize and train the TF-IDF + MultinomialNB classifier."""
    global _classifier_model, _vectorizer
    if _classifier_model is None or _vectorizer is None:
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.naive_bayes import MultinomialNB

            texts = [item[0] for item in TRAINING_DATA]
            labels = [item[1] for item in TRAINING_DATA]

            vec = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", lowercase=True)
            X = vec.fit_transform(texts)
            clf = MultinomialNB(alpha=0.5)
            clf.fit(X, labels)

            _vectorizer = vec
            _classifier_model = clf
        except Exception as e:
            logger.warning(f"Failed to initialize scikit-learn model: {e}")
            return None, None
    return _classifier_model, _vectorizer


def predict_priority(description: str) -> str:
    """Classify priority into High, Medium, or Low based on severity cues."""
    desc_lower = description.lower()
    for kw in HIGH_PRIORITY_KEYWORDS:
        if kw in desc_lower:
            return "high"
    for kw in LOW_PRIORITY_KEYWORDS:
        if kw in desc_lower:
            return "low"
    return "medium"


def classify_text(text: str) -> Tuple[Optional[str], str, float, bool]:
    """Run AI classification on a complaint description.

    Returns:
        (predicted_category_name, predicted_priority, confidence_score, needs_review)
    """
    priority = predict_priority(text)

    clf, vec = get_model()
    if clf is None or vec is None:
        # Fallback if scikit-learn is unavailable
        return "General Administration", priority, 0.0, True

    try:
        X = vec.transform([text])
        probabilities = clf.predict_proba(X)[0]
        max_idx = probabilities.argmax()
        predicted_category = str(clf.classes_[max_idx])
        confidence = float(probabilities[max_idx])

        # Flag for human review if model confidence is below the threshold
        needs_review = confidence < CONFIDENCE_THRESHOLD

        return predicted_category, priority, round(confidence, 3), needs_review
    except Exception as exc:
        logger.error(f"Error during AI classification: {exc}")
        return "General Administration", priority, 0.0, True
