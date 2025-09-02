/* Map Controller - Complete Fixed Version */
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

    init(config) {
        this.config = config;
        console.log('MapController initializing with config:', config);
        this.initMap();
        this.initEventListeners();
    },

    initMap() {
        // Initialize map centered on Brisbane/Gold Coast area
        this.map = L.map('map', {
            center: [-27.9, 153.2], // Between Brisbane and Gold Coast
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

        // IMPORTANT: Add click handler for nearby layers
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
        });

        // Listen for filter button clicks (since they might be added dynamically)
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('filter-btn')) {
                const filterType = e.target.dataset.filter || 'all';
                this.applyFilter(filterType, e.target);
            }
        });
    },

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

        // Update form values
        const form = document.getElementById('mapClickForm');
        if (form) {
            document.getElementById('clickLat').value = lat;
            document.getElementById('clickLng').value = lng;

            // Get selected layers
            const selectedLayerIds = Array.from(this.activeLayers).join(',');
            document.getElementById('selectedLayers').value = selectedLayerIds;

            console.log('Triggering HTMX form submit for nearby layers');

            // Trigger HTMX request
            htmx.trigger(form, 'submit');
        } else {
            console.error('mapClickForm not found');
        }
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

    refreshActivePreviews() {
        clearTimeout(this.refreshTimeout);
        this.refreshTimeout = setTimeout(() => {
            this.activeLayers.forEach(layerId => {
                this.loadLayerPreview(layerId);
            });
        }, 500);
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
            layerItem.classList.remove('layer-active', 'layer-loading');
        }
    },

    async loadLayerPreview(layerId) {
        if (!this.activeLayers.has(layerId)) return;

        // Cancel previous request
        if (this.pendingRequests.has(layerId)) {
            const controller = this.pendingRequests.get(layerId);
            controller.abort();
        }

        const bounds = this.map.getBounds();
        const zoom = this.map.getZoom();

        console.log(`Loading preview for layer ${layerId} at zoom ${zoom}`);

        if (zoom < 10) {
            console.log('Zoom too low for preview');
            this.updateLayerStatus(layerId, 'Zoom in to load', 'warning');
            return;
        }

        const controller = new AbortController();
        this.pendingRequests.set(layerId, controller);

        const url = new URL(this.config.previewUrl, window.location.origin);
        url.searchParams.append('layer_id', layerId);
        url.searchParams.append('minx', bounds.getWest());
        url.searchParams.append('miny', bounds.getSouth());
        url.searchParams.append('maxx', bounds.getEast());
        url.searchParams.append('maxy', bounds.getNorth());

        const layerItem = document.querySelector(`[data-layer-id="${layerId}"]`);
        if (layerItem) {
            layerItem.classList.add('layer-loading');
        }

        try {
            const response = await fetch(url, {
                signal: controller.signal,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            const data = await response.json();
            this.pendingRequests.delete(layerId);

            if (layerItem) {
                layerItem.classList.remove('layer-loading');
            }

            // Remove existing preview
            if (this.previewLayers[layerId]) {
                this.map.removeLayer(this.previewLayers[layerId]);
                delete this.previewLayers[layerId];
            }

            // Add features if any
            if (data.features && data.features.length > 0) {
                console.log(`Adding ${data.features.length} features for layer ${layerId}`);

                const geoJsonLayer = L.geoJSON(data, {
                    style: (feature) => this.getFeatureStyle(feature),
                    pointToLayer: (feature, latlng) => this.createPointMarker(feature, latlng),
                    onEachFeature: (feature, layer) => this.bindFeaturePopup(feature, layer)
                });

                this.previewLayers[layerId] = geoJsonLayer;
                geoJsonLayer.addTo(this.map);

                this.updateLayerStatus(layerId, `${data.features.length} features`, 'success');
            } else {
                const message = data.message || 'No features in view';
                this.updateLayerStatus(layerId, message, 'warning');
            }

        } catch (error) {
            this.pendingRequests.delete(layerId);

            if (layerItem) {
                layerItem.classList.remove('layer-loading');
            }

            if (error.name !== 'AbortError') {
                console.error(`Failed to load preview for layer ${layerId}:`, error);
                this.updateLayerStatus(layerId, 'Load error', 'error');
            }
        }
    },

    updateLayerStatus(layerId, message, type) {
        const statusEl = document.querySelector(`#layer-status-${layerId}`);
        if (statusEl) {
            statusEl.textContent = message;
            statusEl.className = `feature-count status-${type}`;
        }
    },

    getFeatureStyle(feature) {
        const layerName = (feature.properties?.layer_name || '').toLowerCase();

        // Color scheme based on infrastructure type
        if (layerName.includes('water') || layerName.includes('hydrant')) {
            return { color: '#3b82f6', weight: 2, opacity: 0.8, fillOpacity: 0.3 };
        } else if (layerName.includes('sewer') || layerName.includes('waste')) {
            return { color: '#84cc16', weight: 2, opacity: 0.8, fillOpacity: 0.3 };
        } else if (layerName.includes('storm') || layerName.includes('drain')) {
            return { color: '#06b6d4', weight: 2, opacity: 0.8, fillOpacity: 0.3 };
        } else if (layerName.includes('electric') || layerName.includes('power')) {
            return { color: '#f59e0b', weight: 2, opacity: 0.8, fillOpacity: 0.3 };
        } else if (layerName.includes('road') || layerName.includes('street')) {
            return { color: '#6b7280', weight: 3, opacity: 0.8, fillOpacity: 0.2 };
        }
        return { color: '#8b5cf6', weight: 2, opacity: 0.7, fillOpacity: 0.3 };
    },

    createPointMarker(feature, latlng) {
        const style = this.getFeatureStyle(feature);
        return L.circleMarker(latlng, {
            radius: 6,
            fillColor: style.color,
            color: '#fff',
            weight: 1,
            opacity: 1,
            fillOpacity: 0.8
        });
    },

    bindFeaturePopup(feature, layer) {
        const props = feature.properties || {};
        let popupContent = '<div class="feature-popup">';
        popupContent += `<h4>${props.layer_name || 'Feature'}</h4>`;

        const excludeKeys = ['layer_name', 'layer_type', 'layer_id'];
        Object.keys(props).forEach(key => {
            if (!excludeKeys.includes(key) && props[key] !== null) {
                const displayKey = key.replace(/_/g, ' ').toUpperCase();
                popupContent += `<div><strong>${displayKey}:</strong> ${props[key]}</div>`;
            }
        });
        popupContent += '</div>';

        layer.bindPopup(popupContent, {
            maxWidth: 300,
            className: 'custom-popup'
        });
    },

    zoomToLayer(layerId, lat, lng) {
        console.log(`Zooming to layer ${layerId} at ${lat}, ${lng}`);

        // Check for null/invalid coordinates
        if (!lat || !lng || lat === 'null' || lng === 'null' || lat === 'None' || lng === 'None') {
            this.showToast('No location data for this layer', 'warning');
            return;
        }

        lat = parseFloat(lat);
        lng = parseFloat(lng);

        if (isNaN(lat) || isNaN(lng) || lat < -90 || lat > 90 || lng < -180 || lng > 180) {
            this.showToast('Invalid coordinates for this layer', 'error');
            return;
        }

        this.map.setView([lat, lng], 15, {
            animate: true,
            duration: 1.0
        });

        // Flash marker at location
        const marker = L.circleMarker([lat, lng], {
            radius: 12,
            fillColor: '#ff7800',
            color: '#fff',
            weight: 3,
            opacity: 1,
            fillOpacity: 0.8
        }).addTo(this.map);

        // Pulse effect
        let pulseCount = 0;
        const pulseInterval = setInterval(() => {
            pulseCount++;
            marker.setRadius(pulseCount % 2 === 0 ? 12 : 15);
            if (pulseCount >= 6) {
                clearInterval(pulseInterval);
                setTimeout(() => this.map.removeLayer(marker), 500);
            }
        }, 300);

        // Auto-activate layer
        const checkbox = document.getElementById(`layer-${layerId}`);
        if (checkbox && !checkbox.checked) {
            checkbox.checked = true;
            this.toggleLayer(layerId, checkbox);
        }
    },

    updateActiveCount() {
        const count = this.activeLayers.size;
        const countEl = document.getElementById('activeCount');
        if (countEl) {
            countEl.textContent = count > 0 ? `(${count})` : '';
        }
    },

    showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;

        let container = document.getElementById('toastContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toastContainer';
            container.className = 'toast-container';
            document.body.appendChild(container);
        }

        container.appendChild(toast);

        // Animate in
        requestAnimationFrame(() => {
            toast.classList.add('show');
        });

        // Remove after delay
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    },

    applyFilter(filterType, button) {
        console.log('Applying filter:', filterType);

        // Update button states
        document.querySelectorAll('.filter-btn').forEach(btn => {
            btn.classList.remove('active');
        });
        if (button) {
            button.classList.add('active');
        }

        // Update search with filter
        const searchInput = document.getElementById('layerSearch');
        if (searchInput) {
            const currentUrl = searchInput.getAttribute('hx-get');
            const url = new URL(currentUrl, window.location.origin);
            url.searchParams.set('filter', filterType);
            searchInput.setAttribute('hx-get', url.pathname + url.search);

            // Trigger search
            htmx.trigger(searchInput, 'keyup');
        }
    },

    refreshLayers() {
        console.log('Refreshing all active layers');
        this.refreshActivePreviews();
        this.showToast('Refreshing layers...', 'info');
    },

    changeBasemap(mapType) {
        Object.values(this.baseLayers).forEach(layer => {
            this.map.removeLayer(layer);
        });

        if (this.baseLayers[mapType]) {
            this.baseLayers[mapType].addTo(this.map);
            this.showToast(`Switched to ${mapType} map`, 'success');
        }
    },

    toggleBasemapMenu() {
        const menu = document.getElementById('basemapOptions');
        if (menu) {
            menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
        }
    },

    // Nearby layers functions
    openNearbySidebar() {
        console.log('Opening nearby sidebar');
        const sidebar = document.getElementById('nearbySidebar');
        if (sidebar) {
            sidebar.classList.add('open');
        }
    },

    closeNearbySidebar() {
        console.log('Closing nearby sidebar');
        const sidebar = document.getElementById('nearbySidebar');
        if (sidebar) {
            sidebar.classList.remove('open');
        }

        // Remove click marker
        if (this.clickMarker) {
            this.map.removeLayer(this.clickMarker);
            this.clickMarker = null;
        }
    },

    // Download functions
    async downloadArea(layerId, lat, lng) {
        const bounds = this.map.getBounds();
        const selectedLayers = layerId ? [layerId] : Array.from(this.activeLayers);

        if (selectedLayers.length === 0) {
            this.showToast('Please select layers to download', 'warning');
            return;
        }

        // Show loading
        this.showToast('Preparing download...', 'info');

        const formData = new FormData();
        formData.append('csrfmiddlewaretoken', this.config.csrfToken);
        selectedLayers.forEach(id => formData.append('layer_ids[]', id));
        formData.append('minx', bounds.getWest());
        formData.append('miny', bounds.getSouth());
        formData.append('maxx', bounds.getEast());
        formData.append('maxy', bounds.getNorth());
        formData.append('lat', lat || bounds.getCenter().lat);
        formData.append('lng', lng || bounds.getCenter().lng);

        try {
            const response = await fetch(this.config.exportUrl, {
                method: 'POST',
                body: formData
            });

            if (response.ok) {
                const contentType = response.headers.get('content-type');

                if (contentType && contentType.includes('application/dxf')) {
                    // Handle DXF file download
                    const blob = await response.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `layers_export_${new Date().getTime()}.dxf`;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    window.URL.revokeObjectURL(url);

                    this.showToast('Download started successfully!', 'success');
                } else {
                    // Handle JSON error response
                    const data = await response.json();
                    const errorMsg = data.error || 'Export failed';
                    this.showToast(errorMsg, 'error');

                    // Show detailed error if available
                    if (data.details) {
                        console.error('Export error details:', data.details);
                    }
                }
            } else {
                this.showToast('Export request failed', 'error');
            }
        } catch (error) {
            console.error('Download error:', error);
            this.showToast('Download failed. Please try again.', 'error');
        }
    },

    async downloadNearbyLayers() {
        const form = document.getElementById('nearbyDownloadForm');
        if (!form) {
            console.error('Nearby download form not found');
            return;
        }

        const checkedBoxes = form.querySelectorAll('input[name="layer_ids[]"]:checked');
        if (checkedBoxes.length === 0) {
            this.showToast('Please select layers to download', 'warning');
            return;
        }

        this.showToast(`Downloading ${checkedBoxes.length} layers...`, 'info');

        const formData = new FormData(form);
        const bounds = this.map.getBounds();
        formData.append('minx', bounds.getWest());
        formData.append('miny', bounds.getSouth());
        formData.append('maxx', bounds.getEast());
        formData.append('maxy', bounds.getNorth());

        try {
            const response = await fetch(this.config.exportUrl, {
                method: 'POST',
                body: formData
            });

            if (response.ok) {
                const contentType = response.headers.get('content-type');

                if (contentType && contentType.includes('application/dxf')) {
                    const blob = await response.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `nearby_layers_${new Date().getTime()}.dxf`;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    window.URL.revokeObjectURL(url);

                    this.showToast('Download started successfully!', 'success');

                    // Close sidebar after successful download
                    setTimeout(() => this.closeNearbySidebar(), 2000);
                } else {
                    const data = await response.json();
                    this.showToast(data.error || 'Export failed', 'error');
                }
            }
        } catch (error) {
            console.error('Download error:', error);
            this.showToast('Download failed', 'error');
        }
    }
};

// Global function bindings
window.MapController = MapController;
window.toggleLayer = (layerId, checkbox) => MapController.toggleLayer(layerId, checkbox);
window.zoomToLayer = (layerId, lat, lng) => MapController.zoomToLayer(layerId, lat, lng);
window.downloadArea = (layerId, lat, lng) => MapController.downloadArea(layerId, lat, lng);
window.downloadNearbyLayers = () => MapController.downloadNearbyLayers();
window.updateNearbyCount = () => {
    const form = document.getElementById('nearbyDownloadForm');
    if (form) {
        const checked = form.querySelectorAll('input[name="layer_ids[]"]:checked').length;
        const countEl = document.getElementById('nearbyCount');
        if (countEl) {
            countEl.textContent = checked > 0 ? `(${checked})` : '';
        }
    }
};