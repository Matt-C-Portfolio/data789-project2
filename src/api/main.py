"""
FastAPI serving app.

PROVIDED: app setup, model/feature-store load at startup, /health, /model/info,
and the request/response schemas (so input validation → HTTP 422 works for free).
YOU IMPLEMENT: the bodies of /predict and /predict_batch (graded: FastAPI Serving, 16 pts).
"""
from __future__ import annotations

import os
import time
import asyncio
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.api.fraud_detector import FraudDetector
from src.streaming.feature_store import FeatureStore

app = FastAPI(title="TrustBank Fraud Detection API")

# Loaded once at startup (do NOT load the model per-request).
detector = FraudDetector()
store = FeatureStore()
FEATURE_CACHE_SECONDS = 1.0
FEATURE_CACHE_CAPACITY = 1024
feature_cache: dict[str, tuple[float, dict]] = {}


async def customer_features_for_prediction(customer_id: str):
    now = time.monotonic()
    cached = feature_cache.get(customer_id)
    if cached is not None and now < cached[0]:
        return cached[1]

    features = await asyncio.to_thread(store.get_customer_features, customer_id)
    expires = now + FEATURE_CACHE_SECONDS
    if features is not None and expires > time.monotonic():
        current = feature_cache.get(customer_id)
        if current is None or current[0] < expires:
            if current is None and len(feature_cache) >= FEATURE_CACHE_CAPACITY:
                del feature_cache[next(iter(feature_cache))]
            feature_cache[customer_id] = (expires, features)
    return features


class Transaction(BaseModel):
    customer_id: str
    amount: float
    merchant_category: str
    is_online: bool
    timestamp: str
    transaction_id: Optional[str] = None


class FraudPrediction(BaseModel):
    transaction_id: Optional[str] = None
    fraud_probability: float
    is_fraud: int
    model_version: str
    latency_ms: float


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/model/info")
async def model_info():
    return {"model_version": detector.model_version}


@app.post("/predict", response_model=FraudPrediction)
async def predict_fraud(txn: Transaction):
    """TODO (students):
    1. look up customer features:  store.get_customer_features(txn.customer_id)
    2. merge them with the transaction fields into one dict
    3. score:  detector.predict(merged)
    4. measure latency and return a FraudPrediction
    Invalid input already returns HTTP 422 automatically (Pydantic)."""
    
    prediction_start_time = time.perf_counter()    
    
    customer_features = await customer_features_for_prediction(txn.customer_id)
    
    if customer_features is None:
      customer_features = {'transaction_count': 0, 'avg_amount': 0}
    
    transaction_data = txn.model_dump()
    
    prediction_input = transaction_data.copy()
    prediction_input.update(customer_features)
    
    fraud_prediction = await asyncio.to_thread(detector.predict, prediction_input)
    
    prediction_end_time = time.perf_counter()
    prediction_latency_ms = (prediction_end_time - prediction_start_time) * 1000
    
    return FraudPrediction(transaction_id    = txn.transaction_id,
                           fraud_probability = fraud_prediction['fraud_probability'],
                           is_fraud          = fraud_prediction['is_fraud'],
                           model_version     = fraud_prediction['model_version'],
                           latency_ms        = prediction_latency_ms)
      

@app.post("/predict_batch")
async def predict_fraud_batch(txns: List[Transaction]):
    """TODO (students): batch version of /predict — retrieve features for all
    customers in one call (store.get_customer_features_batch) and score each."""
    
    if len(txns) == 0 : return []
    
    customer_ids = []
    for transaction in txns: customer_ids.append(transaction.customer_id)
    
    feature_retrieval_start_time = time.perf_counter()
    customer_features_by_id = await asyncio.to_thread(store.get_customer_features_batch, customer_ids)
    feature_retrieval_seconds = time.perf_counter() - feature_retrieval_start_time
    
    fraud_predictions = []
    
    for transaction in txns:
      prediction_start_time = time.perf_counter()
      
      customer_features = customer_features_by_id.get(transaction.customer_id)
      
      if customer_features is None:
        customer_features = {'transaction_count': 0, 'avg_amount': 0.0}
    
      transaction_data = transaction.model_dump()
      prediction_input = transaction_data.copy()
      prediction_input.update(customer_features)
      
      fraud_prediction = await asyncio.to_thread(detector.predict, prediction_input)

      prediction_seconds = time.perf_counter() - prediction_start_time
      prediction_latency_ms = (feature_retrieval_seconds + prediction_seconds) * 1000

      prediction_response = FraudPrediction(transaction_id    = transaction.transaction_id,
                                            fraud_probability = fraud_prediction["fraud_probability"],
                                            is_fraud          = fraud_prediction["is_fraud"],
                                            model_version     = fraud_prediction["model_version"],
                                            latency_ms        = prediction_latency_ms)

      fraud_predictions.append(prediction_response)
      
    return fraud_predictions
