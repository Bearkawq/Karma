#!/usr/bin/env python3
"""
Lightweight ML Layer - Custom Machine Learning Implementations

Implements from-scratch ML algorithms:
- Naive Bayes classifier for intent classification
- Logistic regression for candidate scoring
- Simple MLP for pattern recognition
No external ML frameworks or pretrained models.
"""

import json
import math
from typing import Dict, List, Any, Tuple
from pathlib import Path


class NaiveBayesClassifier:
    """Naive Bayes classifier for intent classification"""

    def __init__(self):
        self.class_counts = {}
        self.feature_counts = {}
        self.total_count = 0
        self.vocabulary = set()
        self.is_trained = False

    def train(self, training_data: List[Dict[str, Any]]) -> None:
        """Train the Naive Bayes classifier"""
        self.class_counts = {}
        self.feature_counts = {}
        self.total_count = 0
        self.vocabulary = set()

        for example in training_data:
            intent = example.get('intent')
            features = example.get('features', [])

            if intent not in self.class_counts:
                self.class_counts[intent] = 0
            self.class_counts[intent] += 1
            self.total_count += 1

            for feature in features:
                if feature not in self.feature_counts:
                    self.feature_counts[feature] = {}
                if intent not in self.feature_counts[feature]:
                    self.feature_counts[feature][intent] = 0
                self.feature_counts[feature][intent] += 1
                self.vocabulary.add(feature)

        self.is_trained = True

    def classify(self, features: List[str]) -> Tuple[str, float]:
        """Classify input features using Naive Bayes"""
        if not self.is_trained:
            return 'unknown', 0.0

        best_class = None
        best_log_score = float('-inf')
        log_scores: Dict[str, float] = {}

        for class_name, class_count in self.class_counts.items():
            # Log prior
            log_prior = math.log(class_count / self.total_count)

            # Log likelihood with Laplace smoothing
            log_likelihood = 0.0
            for feature in features:
                feature_count = self.feature_counts.get(feature, {}).get(class_name, 0)
                log_likelihood += math.log((feature_count + 1) / (class_count + len(self.vocabulary)))

            log_posterior = log_prior + log_likelihood
            log_scores[class_name] = log_posterior

            if log_posterior > best_log_score:
                best_log_score = log_posterior
                best_class = class_name

        # Softmax confidence: P(best) / sum(P(all))
        if best_class and log_scores:
            # Shift for numerical stability
            max_log = max(log_scores.values())
            exp_sum = sum(math.exp(ls - max_log) for ls in log_scores.values())
            confidence = math.exp(log_scores[best_class] - max_log) / exp_sum
        else:
            confidence = 0.0

        return best_class, confidence

    def save(self, file_path: str) -> None:
        """Save model to file"""
        model_data = {
            'class_counts': self.class_counts,
            'feature_counts': self.feature_counts,
            'total_count': self.total_count,
            'vocabulary': list(self.vocabulary),
            'is_trained': self.is_trained
        }

        with open(file_path, 'w') as f:
            json.dump(model_data, f, indent=2)

    def load(self, file_path: str) -> None:
        """Load model from file"""
        with open(file_path, 'r') as f:
            model_data = json.load(f)

        self.class_counts = model_data.get('class_counts', {})
        self.feature_counts = model_data.get('feature_counts', {})
        self.total_count = model_data.get('total_count', 0)
        self.vocabulary = set(model_data.get('vocabulary', []))
        self.is_trained = model_data.get('is_trained', False)


class LogisticRegression:
    """Logistic regression classifier for candidate scoring"""

    def __init__(self, learning_rate: float = 0.01, epochs: int = 100):
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.weights = {}
        self.intercept = 0.0
        self.classes = []
        self.is_trained = False

    def train(self, training_data: List[Dict[str, Any]]) -> None:
        """Train logistic regression model"""
        if not training_data:
            return

        # Extract features and labels
        features_list = []
        labels = []

        for example in training_data:
            features = example.get('features', {})
            # Accept list or dict; convert list to dict if needed
            if isinstance(features, list):
                features = {str(f): 1.0 for f in features}
            label = example.get('label', 0.0)

            features_list.append(features)
            labels.append(float(label))

            if label not in self.classes:
                self.classes.append(label)

        # Initialize weights from UNION of all feature keys
        all_keys: set = set()
        for f in features_list:
            all_keys.update(f.keys())
        self.weights = {k: 0.0 for k in all_keys}

        # Train using gradient descent
        for epoch in range(self.epochs):
            for i, features in enumerate(features_list):
                label = labels[i]

                # Compute prediction
                prediction = self._predict_proba(features)

                # Compute error
                error = prediction - label

                # Update weights
                for feature, value in features.items():
                    if feature in self.weights:
                        self.weights[feature] -= self.learning_rate * error * float(value)

                # Update intercept
                self.intercept -= self.learning_rate * error

        self.is_trained = True

    def _predict_proba(self, features: Dict[str, float]) -> float:
        """Predict probability using sigmoid"""
        z = self.intercept
        for feature, value in features.items():
            if feature in self.weights:
                z += self.weights[feature] * float(value)

        # Sigmoid with overflow protection
        z = max(-500.0, min(500.0, z))
        return 1.0 / (1.0 + math.exp(-z))

    def predict(self, features: Dict[str, float]) -> float:
        """Predict class probability"""
        if not self.is_trained:
            return 0.5

        return self._predict_proba(features)

    def save(self, file_path: str) -> None:
        """Save model to file"""
        model_data = {
            'weights': self.weights,
            'intercept': self.intercept,
            'classes': self.classes,
            'learning_rate': self.learning_rate,
            'epochs': self.epochs,
            'is_trained': self.is_trained
        }

        with open(file_path, 'w') as f:
            json.dump(model_data, f, indent=2)

    def load(self, file_path: str) -> None:
        """Load model from file"""
        with open(file_path, 'r') as f:
            model_data = json.load(f)

        self.weights = model_data.get('weights', {})
        self.intercept = model_data.get('intercept', 0.0)
        self.classes = model_data.get('classes', [])
        self.learning_rate = model_data.get('learning_rate', 0.01)
        self.epochs = model_data.get('epochs', 100)
        self.is_trained = model_data.get('is_trained', False)


# Seed training data derived from symbolic rules
_SEED_INTENT_DATA = [
    {"text": "list files", "intent": "list_files"},
    {"text": "show my files", "intent": "list_files"},
    {"text": "list all files in home", "intent": "list_files"},
    {"text": "read file config.json", "intent": "read_file"},
    {"text": "read the file named report.txt", "intent": "read_file"},
    {"text": "find files matching *.py", "intent": "search_files"},
    {"text": "search for python files", "intent": "search_files"},
    {"text": "run ls -la", "intent": "run_shell"},
    {"text": "execute echo hello", "intent": "run_shell"},
    {"text": "what can you do", "intent": "list_capabilities"},
    {"text": "golearn python asyncio 5", "intent": "golearn"},
    {"text": "golearn machine learning 3 depth", "intent": "golearn"},
    {"text": "create tool backup bash tar czf", "intent": "create_tool"},
    {"text": "run tool backup", "intent": "run_custom_tool"},
    {"text": "list tools", "intent": "list_custom_tools"},
    {"text": "delete tool backup", "intent": "delete_tool"},
    {"text": "reload language", "intent": "reload_language"},
]


class MLModelManager:
    """Manager for ML models"""

    def __init__(self):
        self.models = {}
        self.model_dir = Path('data/ml_models')
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.training_file = self.model_dir / 'intent_training.jsonl'

    def train_intent_classifier(self, training_data: List[Dict[str, Any]]) -> None:
        """Train intent classifier"""
        classifier = NaiveBayesClassifier()

        # Extract features (simple bag-of-words)
        processed_data = []
        for example in training_data:
            intent = example.get('intent')
            text = example.get('text', '')

            # Simple feature extraction
            features = self._extract_features(text)

            processed_data.append({
                'intent': intent,
                'features': features
            })

        classifier.train(processed_data)
        classifier.save(self.model_dir / 'intent_classifier.json')
        self.models['intent_classifier'] = classifier

    def train_candidate_scorer(self, training_data: List[Dict[str, Any]]) -> None:
        """Train candidate scorer"""
        scorer = LogisticRegression(learning_rate=0.1, epochs=50)

        processed_data = []
        for example in training_data:
            features = example.get('features', {})
            label = example.get('label', 0.0)

            processed_data.append({
                'features': features,
                'label': label
            })

        scorer.train(processed_data)
        scorer.save(self.model_dir / 'candidate_scorer.json')
        self.models['candidate_scorer'] = scorer

    def collect_training_example(self, text: str, intent: str) -> None:
        """Append a successful intent parse to the training file."""
        try:
            import json as _json
            with open(self.training_file, 'a') as f:
                f.write(_json.dumps({"text": text, "intent": intent}) + '\n')
        except Exception:
            pass

    def auto_train(self) -> bool:
        """Auto-train intent classifier from seed data + collected examples."""
        training_data = list(_SEED_INTENT_DATA)
        if self.training_file.exists():
            try:
                with open(self.training_file) as f:
                    for line in f:
                        try:
                            training_data.append(json.loads(line))
                        except (json.JSONDecodeError, ValueError):
                            continue
            except Exception:
                pass
        if len(training_data) < 5:
            return False
        self.train_intent_classifier(training_data)
        return True

    def classify_intent_dict(self, text: str) -> dict:
        """Return intent as a dict with keys: intent, confidence, entities."""
        label, conf = self.classify_intent(text)
        return {"intent": label, "confidence": float(conf), "entities": {}}

    def classify_intent(self, text: str) -> Tuple[str, float]:
        """Classify intent using trained model"""
        if 'intent_classifier' not in self.models:
            self._load_model('intent_classifier')

        classifier = self.models.get('intent_classifier')
        if not classifier:
            return 'unknown', 0.0

        features = self._extract_features(text)
        return classifier.classify(features)

    def score_candidate(self, features: Dict[str, float]) -> float:
        """Score candidate using trained model"""
        if 'candidate_scorer' not in self.models:
            self._load_model('candidate_scorer')

        scorer = self.models.get('candidate_scorer')
        if not scorer:
            return 0.5

        return scorer.predict(features)

    def _extract_features(self, text: str) -> List[str]:
        """Extract simple features from text"""
        # Simple bag-of-words
        words = text.lower().split()
        return [w.strip('.,?!') for w in words if len(w) > 2]

    def _load_model(self, model_name: str) -> None:
        """Load model from file"""
        model_path = self.model_dir / f'{model_name}.json'
        if not model_path.exists():
            return

        if model_name == 'intent_classifier':
            classifier = NaiveBayesClassifier()
            classifier.load(model_path)
            self.models[model_name] = classifier
        elif model_name == 'candidate_scorer':
            scorer = LogisticRegression()
            scorer.load(model_path)
            self.models[model_name] = scorer

    def refine_actions(self, intent: dict, actions: List[dict]) -> List[dict]:
        """Optional ML-based refinement of candidate actions.
        If symbolic confidence >= 0.75, return original order (don't override strong match).
        """
        if not actions:
            return []
        if float(intent.get("confidence", 0)) >= 0.75:
            return actions
        try:
            scored = [(a, self.score_action(a, intent)) for a in actions]
            scored.sort(key=lambda x: x[1], reverse=True)
            return [a for a, _ in scored]
        except Exception:
            return actions

    def score_action(self, action: dict, intent: dict) -> float:
        """Score an action candidate. Uses candidate_scorer if trained; otherwise returns 0.5."""
        try:
            text = " ".join([str(intent.get("intent", "")), str(action.get("name", "")), str(action.get("tool", ""))])
            feats = self._extract_features(text)
            feat_vec = {}
            for w in feats:
                feat_vec[w] = feat_vec.get(w, 0.0) + 1.0
            return float(self.score_candidate(feat_vec))
        except Exception:
            return 0.5

    def is_trained(self, model_name: str) -> bool:
        """Check if model is trained"""
        model = self.models.get(model_name)
        if model:
            return hasattr(model, 'is_trained') and model.is_trained
        return False

    def get_model_info(self, model_name: str) -> Dict[str, Any]:
        """Get model information"""
        model = self.models.get(model_name)
        if not model:
            return { 'exists': False }

        info = {
            'exists': True,
            'is_trained': getattr(model, 'is_trained', False),
            'type': type(model).__name__
        }

        if hasattr(model, 'classes'):
            info['classes'] = getattr(model, 'classes', [])

        return info


# Example ML training and usage
if __name__ == "__main__":
    ml_manager = MLModelManager()

    print("ML Layer Tests:")

    # Example training data
    intent_training_data = [
        { 'text': 'List all files in my directory', 'intent': 'list_files' },
        { 'text': 'Show me the contents of report.txt', 'intent': 'read_file' },
        { 'text': 'Delete the old log file', 'intent': 'delete_file' },
        { 'text': 'Whats the weather today?', 'intent': 'get_weather' },
        { 'text': 'Run the backup script', 'intent': 'run_script' },
        { 'text': 'Create a new directory', 'intent': 'create_directory' },
        { 'text': 'Find all Python files', 'intent': 'find_files' },
        { 'text': 'How much disk space do I have?', 'intent': 'check_disk' },
        { 'text': 'Exit the program', 'intent': 'exit' },
        { 'text': 'Help me with something', 'intent': 'help' }
    ]

    # Train intent classifier
    print("- Training intent classifier...")
    ml_manager.train_intent_classifier(intent_training_data)

    # Test classification
    print("- Testing intent classification:")
    test_cases = [
        ('List files in Documents', 'list_files'),
        ('Read report.txt', 'read_file'),
        ('Delete old logs', 'delete_file'),
        ('Whats my disk usage?', 'check_disk'),
        ('Help me', 'help')
    ]

    for text, expected in test_cases:
        intent, confidence = ml_manager.classify_intent(text)
        print(f"  '{text}' -> {intent} ({confidence:.2f})")

    # Example candidate scoring data
    candidate_training_data = [
        {
            'features': { 'preconditions_met': 1.0, 'cost': 1.0, 'similarity': 0.8 },
            'label': 0.9
        },
        {
            'features': { 'preconditions_met': 0.0, 'cost': 3.0, 'similarity': 0.2 },
            'label': 0.1
        },
        {
            'features': { 'preconditions_met': 1.0, 'cost': 2.0, 'similarity': 0.9 },
            'label': 0.8
        }
    ]

    # Train candidate scorer
    print("- Training candidate scorer...")
    ml_manager.train_candidate_scorer(candidate_training_data)

    # Test scoring
    print("- Testing candidate scoring:")
    test_candidates = [
        { 'preconditions_met': 1.0, 'cost': 1.0, 'similarity': 0.9 },
        { 'preconditions_met': 0.0, 'cost': 3.0, 'similarity': 0.3 },
        { 'preconditions_met': 1.0, 'cost': 2.0, 'similarity': 0.8 }
    ]

    for i, features in enumerate(test_candidates):
        score = ml_manager.score_candidate(features)
        print(f"  Candidate {i+1}: {score:.2f}")

    # Model info
    print("- Model information:")
    print(f"Intent classifier: {ml_manager.get_model_info('intent_classifier')}")
    print(f"Candidate scorer: {ml_manager.get_model_info('candidate_scorer')}")
