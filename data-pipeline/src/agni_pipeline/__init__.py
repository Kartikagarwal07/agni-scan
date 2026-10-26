"""AGNI-SCAN geospatial data pipeline.

Turns locally supplied NASA FIRMS VIIRS detections and user-supplied Punjab
boundaries into the risk-grid GeoJSON defined in docs/DATA_CONTRACT.md.

The risk score is a heuristic *verification-priority* score. It is not a
probability of burning, and zero observed detections never imply zero burning.
"""

__version__ = "0.1.0"
CONTRACT_VERSION = "1.0.0"
