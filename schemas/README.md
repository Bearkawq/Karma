# Data Schemas for Local Autonomous Agent

## Schema Definitions

### Intent Schema
```json
{
  "intent": "string",
  "confidence": "number",
  "entities": {
    "key": "string",
    "value": "string|number|boolean"
  }
}
```

### Action Schema
```json
{
  "name": "string",
  "preconditions": ["string"],
  "effects": ["string"],
  "cost": "number",
  "parameters": {
    "name": "string",
    "type": "string",
    "required": "boolean"
  },
  "failure_modes": ["string"]
}
```

### Task Schema
```json
{
  "id": "string",
  "goal": "string",
  "status": "string",  // pending, in_progress, completed, failed
  "created_at": "string",
  "updated_at": "string",
  "priority": "number",
  "subtasks": ["string"],
  "context": {}
}
```

### Memory Schema
```json
// Episodic Memory
{
  "timestamp": "string",
  "event": "string",
  "context": {},
  "outcome": "string",
  "confidence": "number"
}

// Facts Memory
{
  "key": "string",
  "value": "any",
  "source": "string",
  "confidence": "number",
  "last_updated": "string"
}

// Tool Metadata
{
  "name": "string",
  "category": "string",
  "description": "string",
  "input_schema": {},
  "preconditions": ["string"],
  "effects": ["string"],
  "cost": "number",
  "failure_modes": ["string"]
}
```

### Decision Schema
```json
{
  "cycle": "number",
  "timestamp": "string",
  "state": {},
  "candidates": [
    {
      "action": "string",
      "symbolic_score": "number",
      "ml_score": "number",
      "total_score": "number",
      "preconditions_met": "boolean",
      "reasoning": "string"
    }
  ],
  "selected": "string",
  "outcome": "string",
  "execution_time": "number"
}
```

### ML Model Schema
```json
// Naive Bayes Model
{
  "type": "naive_bayes",
  "classes": ["string"],
  "feature_counts": {},
  "class_counts": {},
  "total_count": "number"
}

// Logistic Regression Model
{
  "type": "logistic_regression",
  "coefficients": {},
  "intercept": "number",
  "classes": ["string"]
}
```

## File Structure

```
schemas/
├── intent.json
├── action.json
├── task.json
├── memory.json
├── decision.json
└── ml_model.json
```

## Usage

These schemas define the structure for:
- Intent classification results
- Action definitions and metadata
- Task management and tracking
- Memory storage (episodic and facts)
- Decision logging and transparency
- ML model persistence

All data is stored in JSON format for portability and readability.