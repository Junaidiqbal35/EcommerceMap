/**
 * MapController - HTMX-integrated Leaflet map controller
 * Handles layer management, map interactions, and HTMX integration
 */

const MapController = (function() {
    'use strict';

    // Private state
    let map = null;
    let config = {};
    let activeLayers = {};
    let previewLayers = {};
    let selectedLayerIds = new Set();
    let basemaps = {};
    let currentBasemap = 'osm';
    let clickMarker = null;

    // Constants
    const DEFAULT_CENTER = [-27.47, 153.02]; // Brisbane, Australia
    const DEFAULT_ZOOM = 10;
    const SEARCH_RADIUS_M = 2000;

    /**
     * Initialize the map controller
     */
    function init(userConfig) {
        config = userConfig || {};
        
        initMap();
        initBasemaps();
        initEventListeners();
        
        console.log('MapController initialized');
    }

    /**
     * Initialize Leaflet map
     */
    function initMap() {
        map = L.map('map', {
            center: DEFAULT_CENTER,
            zoom: DEFAULT_ZOOM,
            zoomControl: true
        });

        // Add geocoder control
        if (L.Control.geocoder) {
            L.Control.geocoder({
                defaultMarkGeocode: false,
                placeholder: 'Search location...'
            }).on('markgeocode', function(e) {
                const bbox = e.geocode.bbox;
                map.fitBounds(bbox);
            }).addTo(map);
        }

        // Map click handler
        map.on('click', handleMapClick);
        
        // Map move handler for preview updates
        map.on('moveend', debounce(updateActivePreviews, 500));
    }

    /**
     * Initialize basemap layers
     */
    function initBasemaps() {
        basemaps = {
            osm: L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap contributors',
                maxZoom: 19
            }),
            satellite: L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
                attribution: '© Esri',
                maxZoom: 19
            }),
            dark: L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
                attribution: '© CARTO',
                maxZoom: 19
            })
        };

        // Add default basemap
        basemaps.osm.addTo(map);
    }

    /**
     * Initialize event listeners
     */
    function initEventListeners() {
        // Listen for connects updates
        document.body.addEventListener('connectsUpdated', function() {
            refreshConnectsDisplay();
        });

        // Listen for layer toggle events from HTMX
        document.body.addEventListener('layerToggled', function(e) {
            if (e.detail && e.detail.layerId) {
                updateLayerPreview(e.detail.layerId, e.detail.checked);
            }
        });
    }

    /**
     * Handle map click - trigger nearby layers search
     */
    function handleMapClick(e) {
        const { lat, lng } = e.latlng;

        // Update click marker
        if (clickMarker) {
            map.removeLayer(clickMarker);
        }
        clickMarker = L.marker([lat, lng], {
            icon: L.divIcon({
                className: 'click-marker',
                html: '<div class="pulse-marker">📍</div>',
                iconSize: [30, 30],
                iconAnchor: [15, 30]
            })
        }).addTo(map);

        // Update hidden form and trigger HTMX request
        document.getElementById('clickLat').value = lat.toFixed(6);
        document.getElementById('clickLng').value = lng.toFixed(6);
        document.getElementById('selectedLayers').value = Array.from(selectedLayerIds).join(',');

        // Trigger the form submission via HTMX
        htmx.trigger('#mapClickForm', 'submit');

        showToast(`Searching layers near ${lat.toFixed(4)}, ${lng.toFixed(4)}...`, 'info');
    }

    /**
     * Toggle layer visibility and preview
     */
    function toggleLayer(layerId, checkbox) {
        const isChecked = checkbox ? checkbox.checked : !selectedLayerIds.has(layerId);

        if (isChecked) {
            selectedLayerIds.add(layerId);
            loadLayerPreview(layerId);
        } else {
            selectedLayerIds.delete(layerId);
            removeLayerPreview(layerId);
        }

        updateActiveCount();
        
        // Dispatch event for other components
        document.body.dispatchEvent(new CustomEvent('layerToggled', {
            detail: { layerId, checked: isChecked }
        }));
    }

    /**
     * Load layer preview on map
     */
    async function loadLayerPreview(layerId) {
        if (!config.previewUrl) return;

        const bounds = map.getBounds();
        const params = new URLSearchParams({
            layer_id: layerId,
            minx: bounds.getWest(),
            miny: bounds.getSouth(),
            maxx: bounds.getEast(),
            maxy: bounds.getNorth(),
            zoom: map.getZoom()
        });

        try {
            const response = await fetch(`${config.previewUrl}?${params}`);
            if (!response.ok) throw new Error('Failed to load preview');

            const geojson = await response.json();

            // Remove existing preview
            if (previewLayers[layerId]) {
                map.removeLayer(previewLayers[layerId]);
            }

            // Add new preview layer
            if (geojson.features && geojson.features.length > 0) {
                previewLayers[layerId] = L.geoJSON(geojson, {
                    style: getLayerStyle(geojson.features[0]?.properties?.layer_type),
                    pointToLayer: function(feature, latlng) {
                        return L.circleMarker(latlng, {
                            radius: 6,
                            fillColor: getLayerColor(feature.properties?.layer_type),
                            color: '#fff',
                            weight: 2,
                            opacity: 1,
                            fillOpacity: 0.7
                        });
                    },
                    onEachFeature: function(feature, layer) {
                        const props = feature.properties || {};
                        layer.bindPopup(`
                            <strong>${props.layer_name || 'Feature'}</strong><br>
                            Type: ${props.layer_type || 'Unknown'}<br>
                            ${props.diameter ? `Diameter: ${props.diameter}mm<br>` : ''}
                            ${props.material ? `Material: ${props.material}<br>` : ''}
                        `);
                    }
                }).addTo(map);

                // Update feature count badge
                updateFeatureCount(layerId, geojson.features.length);
            }

        } catch (error) {
            console.error(`Error loading preview for layer ${layerId}:`, error);
        }
    }

    /**
     * Remove layer preview from map
     */
    function removeLayerPreview(layerId) {
        if (previewLayers[layerId]) {
            map.removeLayer(previewLayers[layerId]);
            delete previewLayers[layerId];
        }
        updateFeatureCount(layerId, 0);
    }

    /**
     * Update all active layer previews (called on map move)
     */
    function updateActivePreviews() {
        selectedLayerIds.forEach(layerId => {
            loadLayerPreview(layerId);
        });
    }

    /**
     * Zoom to a specific layer location
     */
    function zoomToLayer(layerId, lat, lng) {
        if (lat && lng) {
            map.flyTo([lat, lng], 16, {
                duration: 1.5
            });
            
            // Ensure layer is selected and preview is loaded
            if (!selectedLayerIds.has(layerId)) {
                const checkbox = document.getElementById(`layer-check-${layerId}`);
                if (checkbox) {
                    checkbox.checked = true;
                    toggleLayer(layerId, checkbox);
                }
            }
        } else {
            showToast('No location data available for this layer', 'warning');
        }
    }

    /**
     * Download area for a specific layer
     */
    function downloadArea(layerId, lat, lng) {
        if (!lat || !lng) {
            showToast('No location data available', 'error');
            return;
        }

        Swal.fire({
            title: 'Download Layer',
            text: `Download this layer's data as DXF?`,
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Download',
            confirmButtonColor: '#667eea',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                processDownload([layerId], lat, lng);
            }
        });
    }

    /**
     * Download nearby layers
     */
    function downloadNearbyLayers() {
        const checkboxes = document.querySelectorAll('#nearbyContent input[name="layer_ids[]"]:checked');
        const layerIds = Array.from(checkboxes).map(cb => cb.value);

        if (layerIds.length === 0) {
            showToast('Please select at least one layer', 'warning');
            return;
        }

        const lat = parseFloat(document.getElementById('clickLat').value);
        const lng = parseFloat(document.getElementById('clickLng').value);

        processDownload(layerIds, lat, lng);
    }

    /**
     * Process download request
     */
    async function processDownload(layerIds, lat, lng) {
        const offset = 0.01; // ~1km
        const bounds = {
            minx: lng - offset,
            miny: lat - offset,
            maxx: lng + offset,
            maxy: lat + offset
        };

        // Show loading state
        Swal.fire({
            title: 'Preparing Download',
            html: 'Fetching layer data...',
            allowOutsideClick: false,
            showConfirmButton: false,
            didOpen: () => {
                Swal.showLoading();
            }
        });

        try {
            const formData = new FormData();
            layerIds.forEach(id => formData.append('layer_ids[]', id));
            formData.append('minx', bounds.minx);
            formData.append('miny', bounds.miny);
            formData.append('maxx', bounds.maxx);
            formData.append('maxy', bounds.maxy);
            formData.append('lat', lat);
            formData.append('lng', lng);

            const response = await fetch(config.exportUrl, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': config.csrfToken
                },
                body: formData
            });

            // Check content type to determine response type
            const contentType = response.headers.get('content-type');
            
            if (contentType && contentType.includes('application/json')) {
                const data = await response.json();
                if (!data.success) {
                    throw new Error(data.error || 'Download failed');
                }
            } else if (contentType && (contentType.includes('application/dxf') || contentType.includes('application/octet-stream'))) {
                // Download the file
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `gis_export_${new Date().toISOString().slice(0, 10)}.dxf`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                window.URL.revokeObjectURL(url);

                Swal.fire({
                    title: 'Download Complete!',
                    text: `Successfully exported ${layerIds.length} layer(s)`,
                    icon: 'success',
                    confirmButtonColor: '#667eea'
                });

                // Update connects display
                document.body.dispatchEvent(new CustomEvent('connectsUpdated'));
                return;
            }

            throw new Error('Unexpected response type');

        } catch (error) {
            console.error('Download error:', error);
            Swal.fire({
                title: 'Download Failed',
                text: error.message || 'An error occurred during download',
                icon: 'error',
                confirmButtonColor: '#667eea'
            });
        }
    }

    /**
     * Change basemap
     */
    function changeBasemap(name) {
        if (basemaps[currentBasemap]) {
            map.removeLayer(basemaps[currentBasemap]);
        }

        if (basemaps[name]) {
            basemaps[name].addTo(map);
            currentBasemap = name;
        }
    }

    /**
     * Toggle basemap menu visibility
     */
    function toggleBasemapMenu() {
        const options = document.getElementById('basemapOptions');
        if (options) {
            options.style.display = options.style.display === 'none' ? 'block' : 'none';
        }
    }

    /**
     * Filter layers by type
     */
    function filterLayers(type, button) {
        // Update active button state
        document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
        if (button) button.classList.add('active');

        // Trigger HTMX request with filter
        const searchInput = document.getElementById('layerSearch');
        const currentSearch = searchInput ? searchInput.value : '';

        htmx.ajax('GET', `${config.layersUrl}?search=${currentSearch}&type=${type}`, {
            target: '#layerListContent',
            swap: 'innerHTML'
        });
    }

    /**
     * Refresh layers list
     */
    function refreshLayers() {
        htmx.ajax('GET', config.layersUrl, {
            target: '#layerListContent',
            swap: 'innerHTML'
        });
        showToast('Layers refreshed', 'success');
    }

    /**
     * Open nearby sidebar
     */
    function openNearbySidebar() {
        const sidebar = document.getElementById('nearbySidebar');
        if (sidebar) {
            sidebar.classList.add('active');
        }
    }

    /**
     * Close nearby sidebar
     */
    function closeNearbySidebar() {
        const sidebar = document.getElementById('nearbySidebar');
        if (sidebar) {
            sidebar.classList.remove('active');
        }

        // Remove click marker
        if (clickMarker) {
            map.removeLayer(clickMarker);
            clickMarker = null;
        }
    }

    /**
     * Close download modal
     */
    function closeDownloadModal() {
        const modal = document.getElementById('downloadResultModal');
        if (modal) {
            modal.style.display = 'none';
        }
    }

    /**
     * Handle HTMX after swap events
     */
    function handleHtmxAfterSwap(evt) {
        // Update counts after layer list loads
        if (evt.detail.target.id === 'layerListContent') {
            updateActiveCount();
        }
        
        // Update nearby count after nearby layers load
        if (evt.detail.target.id === 'nearbyContent') {
            updateNearbyCount();
        }
    }

    /**
     * Update active layer count display
     */
    function updateActiveCount() {
        const countEl = document.getElementById('activeCount');
        if (countEl) {
            const count = selectedLayerIds.size;
            countEl.textContent = count > 0 ? `(${count} active)` : '';
        }
    }

    /**
     * Update nearby layer count display
     */
    function updateNearbyCount() {
        const countEl = document.getElementById('nearbyCount');
        const checkboxes = document.querySelectorAll('#nearbyContent input[name="layer_ids[]"]:checked');
        if (countEl) {
            countEl.textContent = checkboxes.length > 0 ? `(${checkboxes.length} selected)` : '';
        }
    }

    /**
     * Update feature count badge for a layer
     */
    function updateFeatureCount(layerId, count) {
        const badge = document.querySelector(`#layer-item-${layerId} .feature-count`);
        if (badge) {
            badge.textContent = count > 0 ? count : '';
            badge.style.display = count > 0 ? 'inline-block' : 'none';
        }
    }

    /**
     * Refresh connects display
     */
    function refreshConnectsDisplay() {
        const connectsEl = document.querySelector('.connects-count');
        if (connectsEl && config.connectsUrl) {
            htmx.ajax('GET', config.connectsUrl, {
                target: '.connects-count',
                swap: 'innerHTML'
            });
        }
    }

    /**
     * Get layer style based on type
     */
    function getLayerStyle(type) {
        const styles = {
            polygon: {
                color: '#3388ff',
                weight: 2,
                opacity: 0.8,
                fillOpacity: 0.3
            },
            polyline: {
                color: '#ff7800',
                weight: 3,
                opacity: 0.8
            },
            point: {
                color: '#51bbd6',
                weight: 2,
                opacity: 0.8
            }
        };
        return styles[type] || styles.polyline;
    }

    /**
     * Get layer color based on type
     */
    function getLayerColor(type) {
        const colors = {
            point: '#e74c3c',
            polyline: '#f39c12',
            polygon: '#3498db'
        };
        return colors[type] || '#95a5a6';
    }

    /**
     * Show toast notification
     */
    function showToast(message, type = 'info') {
        const container = document.getElementById('toastContainer');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        
        const icons = {
            success: '✅',
            error: '❌',
            warning: '⚠️',
            info: 'ℹ️'
        };
        
        toast.innerHTML = `
            <span class="toast-icon">${icons[type] || icons.info}</span>
            <span class="toast-message">${message}</span>
        `;
        
        container.appendChild(toast);

        // Animate in
        setTimeout(() => toast.classList.add('show'), 10);

        // Remove after delay
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    /**
     * Debounce utility function
     */
    function debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    // Public API
    return {
        init,
        toggleLayer,
        zoomToLayer,
        downloadArea,
        downloadNearbyLayers,
        changeBasemap,
        toggleBasemapMenu,
        filterLayers,
        refreshLayers,
        openNearbySidebar,
        closeNearbySidebar,
        closeDownloadModal,
        handleHtmxAfterSwap,
        updateNearbyCount,
        showToast,
        
        // Expose map for advanced usage
        getMap: () => map,
        getSelectedLayers: () => Array.from(selectedLayerIds)
    };

})();

// Export for module systems if needed
if (typeof module !== 'undefined' && module.exports) {
    module.exports = MapController;
}