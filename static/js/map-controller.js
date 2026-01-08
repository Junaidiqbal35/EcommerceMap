/* Map Controller - OPTIMIZED VERSION */
/* Removed auto-loading of preferred layers on init */
/* global L, htmx */

const MapController = {
    map: null,
    baseLayers: {},
    previewLayers: {},
    activeLayers: new Set(),
    layerStatus: new Map(),
    pendingRequests: new Map(),
    config: {},
    clickMarker: null,
    preferredLayerIds: [],

    init(config) {
        this.config = config;
        console.log('MapController initializing with config:', config);
        this.initMap();
        this.initEventListeners();

        // ✅ FIXED: Only store preferred IDs, don't auto-activate
        // This prevents the slow API call on page load
        if (window.preferredLayerIds && Array.isArray(window.preferredLayerIds)) {
            this.preferredLayerIds = window.preferredLayerIds;
            console.log('Stored preferred layer IDs (not auto-loading):', this.preferredLayerIds);
        }

        // ❌ REMOVED: setTimeout(() => this.loadPreferredLayers(), 800);
        // This was causing slow page load by triggering external API calls
    },

    initMap() {
        // Initialize map centered on Brisbane/Gold Coast area
        this.map = L.map('map', {
            center: [-27.9, 153.2],
            zoom: 11,
            preferCanvas: true
        });

        // Add base layers
        this.baseLayers = {
            'osm': L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: 'OpenStreetMap',
                maxZoom: 19
            }),
            'satellite': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
                attribution: 'Esri',
                maxZoom: 19
            }),
            'terrain': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}', {
                attribution: 'Esri',
                maxZoom: 19
            }),
            'dark': L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
                attribution: 'CARTO',
                maxZoom: 19
            })
        };

        this.baseLayers.osm.addTo(this.map);
        L.control.scale().addTo(this.map);

        // Map events
        this.map.on('moveend', () => this.onMapMove());
        this.map.on('zoomend', () => this.onMapZoom());

        // Add click handler for nearby layers
        this.map.on('click', (e) => {
            console.log('Map clicked at:', e.latlng);
            this.handleMapClick(e);
        });
    },

    initEventListeners() {
        // Listen for HTMX events
        document.body.addEventListener('htmx:afterSwap', (evt) => {
            console.log('HTMX swap completed');

            // Reinitialize Alpine.js components if needed
            if (window.Alpine && evt.detail.target.querySelector('[x-data]')) {
                window.Alpine.initTree(evt.detail.target);
            }

            // ✅ FIXED: Only mark preferred layers visually (no activation)
            if (evt.detail.target.id === 'layer-list' || evt.detail.target.closest('#layer-list')) {
                setTimeout(() => this.markPreferredLayers(), 100);
            }

            // Open sidebar when nearby content loads
            if (evt.detail.target.id === 'nearbyContent') {
                this.openNearbySidebar();
            }
        });

        // Listen for filter button clicks
        // Filter buttons - use htmx.ajax directly
    let currentFilter = 'all';

    document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', function(e) {
        e.preventDefault();

        // Update active state
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        this.classList.add('active');

        // Get filter type
        currentFilter = this.dataset.filter;
        const searchInput = document.getElementById('layerSearch') || document.getElementById('layer-search');
        const searchValue = searchInput ? searchInput.value : '';

        // Build URL with both search and filter params
        let url = '{% url "layer_list" %}?filter=' + encodeURIComponent(currentFilter);
        if (searchValue) {
            url += '&search=' + encodeURIComponent(searchValue);
        }

        htmx.ajax('GET', url, {
            target: '#layer-list',
            swap: 'innerHTML'
        });
    });
});
    },

    markPreferredLayers() {
        if (!this.preferredLayerIds || this.preferredLayerIds.length === 0) {
            return;
        }

        this.preferredLayerIds.forEach(layerId => {
            const layerItem = document.querySelector(`[data-layer-id="${layerId}"]`);
            if (layerItem) {
                layerItem.classList.add('layer-preferred');
            }
        });

        console.log(`Marked ${this.preferredLayerIds.length} preferred layers (visual only)`);
    },

    // ❌ REMOVED: activateSinglePreferredLayer() function
    // This was causing slow page load by calling loadLayerPreview()

    handleMapClick(e) {
        const lat = e.latlng.lat;
        const lng = e.latlng.lng;

        console.log(`Getting nearby layers for: ${lat}, ${lng}`);

        // Remove previous click marker
        if (this.clickMarker) {
            this.map.removeLayer(this.clickMarker);
        }

        // Add new click marker
        this.clickMarker = L.circleMarker([lat, lng], {
            radius: 8,
            fillColor: '#ff7800',
            color: '#fff',
            weight: 2,
            opacity: 1,
            fillOpacity: 0.8
        }).addTo(this.map);

        // Store clicked location for download
        this.clickedLocation = { lat, lng };

        // Fetch nearby layers directly
        const url = `${this.config.nearbyUrl}?lat=${lat}&lng=${lng}&dist=2000`;

        // Show loading state in sidebar
        const nearbyContent = document.getElementById('nearbyContent');
        if (nearbyContent) {
            nearbyContent.innerHTML = '<div class="htmx-indicator" style="display:flex;"><div class="loading-spinner"></div></div>';
        }

        // Open sidebar immediately
        this.openNearbySidebar();

        fetch(url, {
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': this.config.csrfToken
            }
        })
        .then(response => {
            if (!response.ok) throw new Error('Network response was not ok');
            return response.text();
        })
        .then(html => {
            if (nearbyContent) {
                nearbyContent.innerHTML = html;
            }
        })
        .catch(error => {
            console.error('Error fetching nearby layers:', error);
            if (nearbyContent) {
                nearbyContent.innerHTML = `
                    <div class="nearby-error">
                        <div class="error-icon">⚠️</div>
                        <p class="error-message">Failed to load nearby layers</p>
                    </div>`;
            }
            this.showToast('Failed to load nearby layers', 'error');
        });
    },

    onMapMove() {
        this.refreshActivePreviews();
    },

    onMapZoom() {
        const zoom = this.map.getZoom();
        console.log('Map zoom:', zoom);

        if (zoom < 12 && this.activeLayers.size > 0) {
            this.showToast('Zoom in closer to see layer features', 'info');
        }
        this.refreshActivePreviews();
    },

    // ✅ OPTIMIZED: Increased debounce time from 500ms to 1000ms
    refreshActivePreviews() {
        clearTimeout(this.refreshTimeout);
        this.refreshTimeout = setTimeout(() => {
            this.activeLayers.forEach(layerId => {
                this.loadLayerPreview(layerId);
            });
        }, 1000); // Changed from 500ms to 1000ms
    },

    toggleLayer(layerId, checkbox) {
        console.log(`Toggling layer ${layerId}: ${checkbox.checked}`);

        if (checkbox.checked) {
            this.activateLayer(layerId);
        } else {
            this.deactivateLayer(layerId);
        }
        this.updateActiveCount();
    },

    activateLayer(layerId) {
        console.log(`Activating layer ${layerId}`);
        this.activeLayers.add(layerId);

        const layerItem = document.querySelector(`[data-layer-id="${layerId}"]`);
        if (layerItem) {
            layerItem.classList.add('layer-active');
        }

        this.loadLayerPreview(layerId);
    },

    deactivateLayer(layerId) {
        console.log(`Deactivating layer ${layerId}`);
        this.activeLayers.delete(layerId);

        if (this.previewLayers[layerId]) {
            this.map.removeLayer(this.previewLayers[layerId]);
            delete this.previewLayers[layerId];
        }

        if (this.pendingRequests.has(layerId)) {
            const controller = this.pendingRequests.get(layerId);
            controller.abort();
            this.pendingRequests.delete(layerId);
        }

        const layerItem = document.querySelector(`[data-layer-id="${layerId}"]`);
        if (layerItem) {
            layerItem.classList.remove('layer-active');
        }
    },

    async loadLayerPreview(layerId) {
        const bounds = this.map.getBounds();
        const zoom = this.map.getZoom();

        // ✅ OPTIMIZED: Skip if zoomed out too far (changed from 10 to 12)
        if (zoom < 12) {
            console.log(`Zoom ${zoom} too low, skipping preview for layer ${layerId}`);
            this.showToast('Zoom in closer to load layer preview', 'info');
            return;
        }

        // Cancel any pending request for this layer
        if (this.pendingRequests.has(layerId)) {
            this.pendingRequests.get(layerId).abort();
        }

        const controller = new AbortController();
        this.pendingRequests.set(layerId, controller);

        this.updateLayerStatus(layerId, 'loading');

        try {
            const params = new URLSearchParams({
                layer_id: layerId,
                minx: bounds.getWest(),
                miny: bounds.getSouth(),
                maxx: bounds.getEast(),
                maxy: bounds.getNorth()
            });

            const response = await fetch(`${this.config.previewUrl}?${params}`, {
                signal: controller.signal
            });

            if (!response.ok) throw new Error('Failed to fetch preview');

            const geojson = await response.json();

            // Remove existing preview
            if (this.previewLayers[layerId]) {
                this.map.removeLayer(this.previewLayers[layerId]);
            }

            // Add new preview
            if (geojson.features && geojson.features.length > 0) {
                const layer = L.geoJSON(geojson, {
                    style: this.getLayerStyle(geojson.features[0]?.properties?.layer_type),
                    pointToLayer: (feature, latlng) => {
                        return L.circleMarker(latlng, {
                            radius: 6,
                            fillColor: this.getLayerColor(feature.properties?.layer_type),
                            color: '#fff',
                            weight: 2,
                            fillOpacity: 0.8
                        });
                    },
                    onEachFeature: (feature, layer) => {
                        if (feature.properties) {
                            let popup = `<strong>${feature.properties.layer_name || 'Feature'}</strong>`;
                            if (feature.properties.layer_type) {
                                popup += `<br>Type: ${feature.properties.layer_type}`;
                            }
                            layer.bindPopup(popup);
                        }
                    }
                });

                layer.addTo(this.map);
                this.previewLayers[layerId] = layer;
                this.updateLayerStatus(layerId, 'loaded', geojson.features.length);
            } else {
                this.updateLayerStatus(layerId, 'empty');
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                console.log(`Request for layer ${layerId} was aborted`);
            } else {
                console.error(`Error loading layer ${layerId}:`, error);
                this.updateLayerStatus(layerId, 'error');
            }
        } finally {
            this.pendingRequests.delete(layerId);
        }
    },

    updateLayerStatus(layerId, status, featureCount = 0) {
        this.layerStatus.set(layerId, { status, featureCount });

        const layerItem = document.querySelector(`[data-layer-id="${layerId}"]`);
        if (!layerItem) return;

        // Remove old status classes
        layerItem.classList.remove('loading', 'error', 'empty');

        // Add status indicator
        let statusEl = layerItem.querySelector('.layer-status');
        if (!statusEl) {
            statusEl = document.createElement('span');
            statusEl.className = 'layer-status';
            layerItem.querySelector('.layer-info')?.appendChild(statusEl);
        }

        switch (status) {
            case 'loading':
                statusEl.innerHTML = '⏳';
                statusEl.title = 'Loading...';
                layerItem.classList.add('loading');
                break;
            case 'loaded':
                statusEl.innerHTML = `✓ ${featureCount}`;
                statusEl.title = `${featureCount} features loaded`;
                break;
            case 'empty':
                statusEl.innerHTML = '∅';
                statusEl.title = 'No features in view';
                layerItem.classList.add('empty');
                break;
            case 'error':
                statusEl.innerHTML = '⚠️';
                statusEl.title = 'Failed to load';
                layerItem.classList.add('error');
                break;
        }
    },

    updateActiveCount() {
        const count = this.activeLayers.size;
        const countEl = document.getElementById('activeLayerCount');
        const fabEl = document.getElementById('exportFab');

        if (countEl) {
            countEl.textContent = count;
        }

        if (fabEl) {
            fabEl.style.display = count > 0 ? 'flex' : 'none';
        }
    },

    getLayerStyle(layerType) {
        const styles = {
            'point': { color: '#e74c3c', weight: 2, fillOpacity: 0.7 },
            'polyline': { color: '#3498db', weight: 3, fillOpacity: 0 },
            'polygon': { color: '#27ae60', weight: 2, fillOpacity: 0.3 }
        };
        return styles[layerType] || { color: '#9b59b6', weight: 2, fillOpacity: 0.5 };
    },

    getLayerColor(layerType) {
        const colors = {
            'point': '#e74c3c',
            'polyline': '#3498db',
            'polygon': '#27ae60'
        };
        return colors[layerType] || '#9b59b6';
    },

    applyFilter(filterType, clickedBtn) {
        console.log('Applying filter:', filterType);

        // Update active button state
        document.querySelectorAll('.filter-btn').forEach(btn => {
            btn.classList.remove('active');
        });
        clickedBtn.classList.add('active');

        // Trigger HTMX request to reload layer list with filter
        const layerList = document.getElementById('layer-list');
        const searchInput = document.getElementById('layerSearch');

        const params = new URLSearchParams();
        params.set('filter', filterType);
        if (searchInput && searchInput.value) {
            params.set('search', searchInput.value);
        }

        // Update URL and trigger HTMX
        const url = `${this.config.layerListUrl}?${params}`;
        htmx.ajax('GET', url, {target: '#layer-list', swap: 'innerHTML'});
    },

    openNearbySidebar() {
        const sidebar = document.getElementById('nearbySidebar');
        const overlay = document.getElementById('sidebarOverlay');
        if (sidebar) {
            sidebar.classList.add('open');
        }
        if (overlay) {
            overlay.classList.add('show');
        }
    },

    closeNearbySidebar() {
        const sidebar = document.getElementById('nearbySidebar');
        const overlay = document.getElementById('sidebarOverlay');
        if (sidebar) {
            sidebar.classList.remove('open');
        }
        if (overlay) {
            overlay.classList.remove('show');
        }

        // Remove click marker
        if (this.clickMarker) {
            this.map.removeLayer(this.clickMarker);
            this.clickMarker = null;
        }
    },

    showToast(message, type = 'info') {
        // Simple toast notification
        const existingToast = document.querySelector('.map-toast');
        if (existingToast) {
            existingToast.remove();
        }

        const toast = document.createElement('div');
        toast.className = `map-toast toast-${type}`;
        toast.innerHTML = message;
        toast.style.cssText = `
            position: fixed;
            bottom: 100px;
            left: 50%;
            transform: translateX(-50%);
            background: ${type === 'error' ? '#ef4444' : type === 'success' ? '#10b981' : '#3b82f6'};
            color: white;
            padding: 12px 24px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
            z-index: 9999;
            font-size: 14px;
            animation: slideUp 0.3s ease;
        `;

        document.body.appendChild(toast);

        setTimeout(() => {
            toast.style.animation = 'slideDown 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    },

    switchBasemap(name) {
        // Remove current basemap
        Object.values(this.baseLayers).forEach(layer => {
            if (this.map.hasLayer(layer)) {
                this.map.removeLayer(layer);
            }
        });

        // Add selected basemap
        if (this.baseLayers[name]) {
            this.baseLayers[name].addTo(this.map);
        }
    },

    async downloadArea() {
        if (this.activeLayers.size === 0) {
            this.showToast('Select at least one layer first', 'error');
            return;
        }

        const bounds = this.map.getBounds();
        const layerIds = Array.from(this.activeLayers);

        this.showToast('Preparing download...', 'info');

        try {
            const formData = new FormData();
            layerIds.forEach(id => formData.append('layer_ids[]', id));
            formData.append('minx', bounds.getWest());
            formData.append('miny', bounds.getSouth());
            formData.append('maxx', bounds.getEast());
            formData.append('maxy', bounds.getNorth());

            const response = await fetch(this.config.exportUrl, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-CSRFToken': this.config.csrfToken
                }
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Download failed');
            }

            // Download the file
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `layers_export_${new Date().toISOString().slice(0,10)}.dxf`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);

            this.showToast('Download complete!', 'success');
        } catch (error) {
            console.error('Download error:', error);
            this.showToast(error.message || 'Download failed', 'error');
        }
    }
};

// Global functions for onclick handlers in templates
function toggleLayer(layerId, checkbox) {
    MapController.toggleLayer(layerId, checkbox);
}

function zoomToLayer(layerId, lat, lng) {
    if (MapController.map && lat && lng) {
        MapController.map.flyTo([lat, lng], 15);
    }
}

function toggleMinimize() {
    const panel = document.getElementById('layerPanel');
    const icon = document.getElementById('minimizeIcon');
    if (panel) {
        panel.classList.toggle('minimized');
        if (icon) {
            icon.textContent = panel.classList.contains('minimized') ? '+' : '−';
        }
    }
}

function refreshLayers() {
    const layerList = document.getElementById('layer-list');
    if (layerList) {
        htmx.trigger(layerList, 'htmx:trigger');
    }
}

function toggleBasemapOptions() {
    const options = document.getElementById('basemapOptions');
    if (options) {
        options.classList.toggle('show');
    }
}

function updateNearbyCount() {
    const checkboxes = document.querySelectorAll('#nearbyDownloadForm input[type="checkbox"]:checked');
    const countEl = document.getElementById('nearbyCount');
    if (countEl) {
        countEl.textContent = `(${checkboxes.length})`;
    }
}

async function downloadNearbyLayers() {
    const form = document.getElementById('nearbyDownloadForm');
    if (!form) return;

    const formData = new FormData(form);
    const layerIds = formData.getAll('layer_ids[]');

    if (layerIds.length === 0) {
        MapController.showToast('Select at least one layer', 'error');
        return;
    }

    MapController.showToast('Preparing download...', 'info');

    try {
        const response = await fetch(MapController.config.exportUrl, {
            method: 'POST',
            body: formData,
            headers: {
                'X-CSRFToken': MapController.config.csrfToken
            }
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Download failed');
        }

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `nearby_layers_${new Date().toISOString().slice(0,10)}.dxf`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        MapController.showToast('Download complete!', 'success');
        MapController.closeNearbySidebar();
    } catch (error) {
        console.error('Download error:', error);
        MapController.showToast(error.message || 'Download failed', 'error');
    }
}