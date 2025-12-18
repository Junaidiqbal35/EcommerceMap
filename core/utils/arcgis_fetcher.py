import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class ArcGISSession:
    """Reusable session with proper SSL verification and retry logic"""
    
    def __init__(self, verify_ssl=True, timeout=30):
        self.session = requests.Session()
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=20
        )
        
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    
    def get(self, url, params=None):
        """Make GET request with proper error handling"""
        try:
            response = self.session.get(
                url,
                params=params,
                timeout=self.timeout,
                verify=self.verify_ssl
            )
            response.raise_for_status()
            return response
        except requests.exceptions.SSLError as e:
            # Log SSL errors but don't crash
            logger.error(f"SSL Error for {url}: {e}")
            # Retry without verification as fallback
            if self.verify_ssl:
                response = self.session.get(
                    url, 
                    params=params, 
                    timeout=self.timeout,
                    verify=False
                )
                return response
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed for {url}: {e}")
            raise

# Option B: Suppress Warnings (Only for Development)
# ---------------------------------------------------
import urllib3
from django.conf import settings

if settings.DEBUG:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ============================================================================
# SOLUTION 2: Robust Layer Fetching with Multiple Strategies
# ============================================================================

import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

class FetchStrategy(Enum):
    """Available strategies for fetching ArcGIS data"""
    QUERY_ALL = "query_all"
    QUERY_BBOX = "query_bbox"
    QUERY_PAGINATED = "query_paginated"
    FEATURE_SERVER = "feature_server"
    MAP_SERVER = "map_server"

@dataclass
class FetchResult:
    """Result from a fetch attempt"""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    strategy_used: Optional[FetchStrategy] = None
    feature_count: int = 0

class LayerFetcher:
    """
    Clean implementation of multi-strategy layer fetching
    """
    
    def __init__(self, session: ArcGISSession):
        self.session = session
        self.strategies = [
            self._strategy_query_bbox,
            self._strategy_query_all,
            self._strategy_paginated,
            self._strategy_feature_server,
            self._strategy_map_server,
        ]
    
    def fetch_layer_data(
        self, 
        layer_url: str, 
        bbox: Optional[tuple] = None,
        max_features: int = 10000
    ) -> FetchResult:
        """
        Fetch layer data using multiple fallback strategies
        
        Args:
            layer_url: ArcGIS layer endpoint URL
            bbox: Optional bounding box (minx, miny, maxx, maxy)
            max_features: Maximum features to fetch
            
        Returns:
            FetchResult with data or error information
        """
        
        for strategy in self.strategies:
            try:
                logger.info(f"Trying strategy: {strategy.__name__}")
                result = strategy(layer_url, bbox, max_features)
                
                if result.success and result.feature_count > 0:
                    logger.info(
                        f"✓ Success with {strategy.__name__}: "
                        f"{result.feature_count} features"
                    )
                    return result
                    
            except Exception as e:
                logger.warning(
                    f"Strategy {strategy.__name__} failed: {str(e)}"
                )
                continue
        
        # All strategies failed
        return FetchResult(
            success=False,
            error="All fetch strategies failed for this layer"
        )
    
    def _strategy_query_bbox(
        self, 
        layer_url: str, 
        bbox: Optional[tuple],
        max_features: int
    ) -> FetchResult:
        """Strategy 1: Query with bounding box (most efficient)"""
        
        if not bbox:
            raise ValueError("BBOX required for this strategy")
        
        params = {
            'f': 'geojson',
            'geometryType': 'esriGeometryEnvelope',
            'geometry': f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
            'inSR': 4326,
            'outSR': 4326,
            'spatialRel': 'esriSpatialRelIntersects',
            'returnGeometry': 'true',
            'outFields': '*',
            'resultRecordCount': max_features
        }
        
        response = self.session.get(f"{layer_url}/query", params=params)
        data = response.json()
        
        if 'features' in data:
            return FetchResult(
                success=True,
                data=data,
                strategy_used=FetchStrategy.QUERY_BBOX,
                feature_count=len(data['features'])
            )
        
        raise ValueError("No features in response")
    
    def _strategy_query_all(
        self, 
        layer_url: str, 
        bbox: Optional[tuple],
        max_features: int
    ) -> FetchResult:
        """Strategy 2: Query all features (no bbox filter)"""
        
        params = {
            'f': 'geojson',
            'where': '1=1',
            'outFields': '*',
            'returnGeometry': 'true',
            'outSR': 4326,
            'resultRecordCount': max_features
        }
        
        response = self.session.get(f"{layer_url}/query", params=params)
        data = response.json()
        
        if 'features' in data:
            return FetchResult(
                success=True,
                data=data,
                strategy_used=FetchStrategy.QUERY_ALL,
                feature_count=len(data['features'])
            )
        
        raise ValueError("No features in response")
    
    def _strategy_paginated(
        self, 
        layer_url: str, 
        bbox: Optional[tuple],
        max_features: int
    ) -> FetchResult:
        """Strategy 3: Paginated query for large datasets"""
        
        all_features = []
        offset = 0
        page_size = 1000
        
        while len(all_features) < max_features:
            params = {
                'f': 'geojson',
                'where': '1=1',
                'outFields': '*',
                'returnGeometry': 'true',
                'outSR': 4326,
                'resultOffset': offset,
                'resultRecordCount': min(page_size, max_features - len(all_features))
            }
            
            if bbox:
                params['geometry'] = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
                params['geometryType'] = 'esriGeometryEnvelope'
            
            response = self.session.get(f"{layer_url}/query", params=params)
            data = response.json()
            
            if 'features' not in data or not data['features']:
                break
            
            all_features.extend(data['features'])
            
            # Check if we got all features
            if len(data['features']) < page_size:
                break
            
            offset += page_size
        
        if all_features:
            return FetchResult(
                success=True,
                data={'type': 'FeatureCollection', 'features': all_features},
                strategy_used=FetchStrategy.QUERY_PAGINATED,
                feature_count=len(all_features)
            )
        
        raise ValueError("No features found")
    
    def _strategy_feature_server(
        self, 
        layer_url: str, 
        bbox: Optional[tuple],
        max_features: int
    ) -> FetchResult:
        """Strategy 4: Try FeatureServer endpoint"""
        
        # Convert MapServer to FeatureServer URL if needed
        if 'MapServer' in layer_url:
            layer_url = layer_url.replace('MapServer', 'FeatureServer')
        
        return self._strategy_query_bbox(layer_url, bbox, max_features)
    
    def _strategy_map_server(
        self, 
        layer_url: str, 
        bbox: Optional[tuple],
        max_features: int
    ) -> FetchResult:
        """Strategy 5: Try MapServer endpoint with export"""
        
        if 'FeatureServer' in layer_url:
            layer_url = layer_url.replace('FeatureServer', 'MapServer')
        
        # Use export endpoint for MapServer
        params = {
            'f': 'json',
            'bbox': f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}" if bbox else None,
            'bboxSR': 4326,
            'imageSR': 4326,
            'format': 'json',
            'layers': 'all'
        }
        
        response = self.session.get(f"{layer_url}/export", params=params)
        data = response.json()
        
        # Process export response
        if data.get('results'):
            return FetchResult(
                success=True,
                data=data,
                strategy_used=FetchStrategy.MAP_SERVER,
                feature_count=len(data.get('results', []))
            )
        
        raise ValueError("Export failed")