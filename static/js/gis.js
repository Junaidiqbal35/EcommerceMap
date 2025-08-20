(function () {
    'use strict';

    window.gisApp = window.gisApp || {};

    // Configuration
    const CONFIG = {
        MAP_CENTER: [-27.47, 153.02],
        MAP_ZOOM: 10,
        SEARCH_RADIUS: 2000,
        DEBOUNCE_DELAY: 300,
        FEATURE_LOAD_PAD: 0.3,
        MAX_DOWNLOAD_AREA: 0.001,
        URLS: {
            ALL_LAYERS: '/all-layers/',
            LAYER_FEATURES: '/layer-preview-features/',
            NEARBY_LAYERS: '/nearby-layers/',
            EXPORT_DXF: '/export-dxf-multi/',
            CHECK_CONNECTS: '/check-connects/'
        }
    };

    const state = {
        map: null,
        layers: [],
        activeLayers: {},
        basemaps: {},
        currentBasemap: 'osm',
        clickedLocation: null,
        userConnects: 0,
        selectedNearbyLayers: new Set()
    };

    // Get CSRF token
    function getCSRFToken() {
        const cookies = document.cookie.split(';');
        for (let cookie of cookies) {
            const [name, value] = cookie.trim().split('=');
            if (name === 'csrftoken') {
                return value;
            }
        }
        return null;
    }

    // Toast Notification System
    const Toast = {
        container: null,

        init() {
            if (!this.container) {
                this.container = document.createElement('div');
                this.container.className = 'toast-container';
                document.body.appendChild(this.container);
            }
        },

        show(title, message, type = 'info', duration = 3000) {
            this.init();

            const toast = document.createElement('div');
            toast.className = `toast ${type}`;

            const icons = {
                success: '✓',
                error: '✕',
                warning: '⚠',
                info: 'ℹ'
            };

            toast.innerHTML = `
                <div class="toast-icon">${icons[type]}</div>
                <div class="toast-content">
                    <div class="toast-title">${title}</div>
                    <div class="toast-message">${message}</div>
                </div>
                <button class="toast-close">×</button>
            `;

            this.container.appendChild(toast);

            const closeBtn = toast.querySelector('.toast-close');
            closeBtn.onclick = () => this.remove(toast);

            setTimeout(() => this.remove(toast), duration);
        },

        remove(toast) {
            toast.style.animation = 'toastSlideOut 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }
    };

    // Modal System for Confirmations
    const Modal = {
        show(options) {
            const overlay = document.createElement('div');
            overlay.className = 'modal-overlay';

            const content = document.createElement('div');
            content.className = 'modal-content';

            content.innerHTML = `
                <div class="modal-header">
                    <div class="modal-icon">${options.icon || '💾'}</div>
                    <div class="modal-title">
                        <h3>${options.title}</h3>
                        <p>${options.subtitle || ''}</p>
                    </div>
                </div>
                <div class="modal-body">
                    ${options.body}
                </div>
                <div class="modal-footer">
                    <button class="btn-modal btn-cancel">Cancel</button>
                    <button class="btn-modal btn-confirm">${options.confirmText || 'Confirm'}</button>
                </div>
            `;

            overlay.appendChild(content);
            document.body.appendChild(overlay);

            // Show animation
            setTimeout(() => overlay.classList.add('active'), 10);

            // Button handlers
            const cancelBtn = content.querySelector('.btn-cancel');
            const confirmBtn = content.querySelector('.btn-confirm');

            cancelBtn.onclick = () => {
                this.close(overlay);
                if (options.onCancel) options.onCancel();
            };

            confirmBtn.onclick = () => {
                this.close(overlay);
                if (options.onConfirm) options.onConfirm();
            };

            // Close on overlay click
            overlay.onclick = (e) => {
                if (e.target === overlay) {
                    this.close(overlay);
                    if (options.onCancel) options.onCancel();
                }
            };
        },

        close(overlay) {
            overlay.classList.remove('active');
            setTimeout(() => overlay.remove(), 300);
        }
    };

    // Progress indicator for downloads
    const Progress = {
        element: null,

        show(title = 'Downloading...') {
            if (!this.element) {
                this.element = document.createElement('div');
                this.element.className = 'download-progress';
                this.element.innerHTML = `
                    <div class="progress-header">
                        <span class="progress-title">${title}</span>
                        <span class="progress-status">Preparing...</span>
                    </div>
                    <div class="progress-bar">
                        <div class="progress-fill"></div>
                    </div>
                `;
                document.body.appendChild(this.element);
            }

            this.element.classList.add('active');
            this.update(0, 'Preparing...');
        },

        update(percent, status) {
            if (this.element) {
                const fill = this.element.querySelector('.progress-fill');
                const statusEl = this.element.querySelector('.progress-status');
                fill.style.width = `${percent}%`;
                statusEl.textContent = status;
            }
        },

        hide() {
            if (this.element) {
                this.element.classList.remove('active');
            }
        }
    };

    // Initialize application
    async function init() {
        initMap();
        await loadLayers();
        await checkUserConnects();
        bindEvents();

        Toast.show('Welcome!', 'Select layers to view or click on map to find nearby layers', 'info');
    }

    function initMap() {
        state.map = L.map('map', {
            preferCanvas: true,
            updateWhenZooming: false,
            updateWhenIdle: true
        }).setView(CONFIG.MAP_CENTER, CONFIG.MAP_ZOOM);

        setupBasemaps();
        state.basemaps.osm.addTo(state.map);

        // Add hash for URL
        new L.Hash(state.map);

        // Add geocoder
        L.Control.geocoder({
            defaultMarkGeocode: false,
            placeholder: 'Search location...'
        }).on('markgeocode', function (e) {
            const bbox = e.geocode.bbox;
            const poly = L.polygon([
                bbox.getSouthEast(),
                bbox.getNorthEast(),
                bbox.getNorthWest(),
                bbox.getSouthWest()
            ]);
            state.map.fitBounds(poly.getBounds());
            Toast.show('Location Found', `Moved to ${e.geocode.name}`, 'success');
        }).addTo(state.map);

        // Map click for nearby layers
        state.map.on('click', handleMapClick);

        // Move handler for features
        const moveHandler = debounce(() => {
            updateAllLayerFeatures();
        }, CONFIG.DEBOUNCE_DELAY);

        state.map.on('moveend', moveHandler);
    }

    function setupBasemaps() {
        state.basemaps.osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap',
            maxZoom: 19
        });

        state.basemaps.terrain = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}', {
            attribution: '© Esri',
            maxZoom: 19
        });

        state.basemaps.dark = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png', {
            attribution: '© CARTO',
            maxZoom: 19
        });
    }

    async function loadLayers() {
        try {
            const response = await fetch(CONFIG.URLS.ALL_LAYERS);
            if (!response.ok) throw new Error('Failed to load layers');

            state.layers = await response.json();
            renderLayerList();
            updateStats();
        } catch (error) {
            console.error('Error loading layers:', error);
            Toast.show('Error', 'Failed to load layers. Please refresh.', 'error');
        }
    }

    async function checkUserConnects() {
        try {
            const response = await fetch(CONFIG.URLS.CHECK_CONNECTS);
            const data = await response.json();
            state.userConnects = data.connects || 0;
            updateConnectsDisplay();
        } catch (error) {
            console.error('Error checking connects:', error);
        }
    }

    function updateConnectsDisplay() {
        // Update connects display in UI
        const connectsElements = document.querySelectorAll('.user-connects');
        connectsElements.forEach(el => {
            el.textContent = state.userConnects;
        });
    }

    function renderLayerList() {
        const container = document.getElementById('layerList');

        if (!state.layers.length) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📍</div>
                    <div class="empty-state-title">No Layers Available</div>
                    <div class="empty-state-message">Check back later for available layers</div>
                </div>
            `;
            return;
        }

        // Add search box
        let html = `
            <div class="layer-search">
                <input type="text" placeholder="Search layers..." id="layerSearchInput">
                <span class="layer-search-icon">🔍</span>
            </div>
        `;

        // Group by server
        const grouped = {};
        state.layers.forEach(layer => {
            const server = layer.server_name || 'Unknown';
            if (!grouped[server]) grouped[server] = [];
            grouped[server].push(layer);
        });

        Object.entries(grouped).forEach(([serverName, layers]) => {
            html += `
                <div class="server-group">
                    <div class="server-header">${serverName} (${layers.length})</div>
                    ${layers.map(layer => `
                        <div class="layer-item ${state.activeLayers[layer.id] ? 'active' : ''}" 
                             data-layer-id="${layer.id}"
                             data-layer-name="${layer.name.toLowerCase()}">
                            <input type="checkbox" 
                                   class="layer-checkbox" 
                                   id="layer-${layer.id}"
                                   ${state.activeLayers[layer.id] ? 'checked' : ''}
                                   onclick="event.stopPropagation(); gisApp.toggleLayer(${layer.id})">
                            <div class="layer-info">
                                <div class="layer-name" title="${layer.name}">${layer.name}</div>
                                <div class="layer-meta">
                                    <span class="layer-type">${getTypeIcon(layer.type)} ${layer.type}</span>
                                    <span class="feature-count" id="count-${layer.id}"></span>
                                </div>
                            </div>
                            ${layer.centroid_lat ? 
                                `<button class="btn-zoom" onclick="event.stopPropagation(); gisApp.zoomToLayer(${layer.id})" title="Zoom to layer">📍</button>` 
                                : ''}
                        </div>
                    `).join('')}
                </div>
            `;
        });

        container.innerHTML = html;

        // Setup search functionality
        const searchInput = document.getElementById('layerSearchInput');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                const searchTerm = e.target.value.toLowerCase();
                document.querySelectorAll('.layer-item').forEach(item => {
                    const name = item.dataset.layerName;
                    item.style.display = name.includes(searchTerm) ? 'flex' : 'none';
                });
            });
        }
    }

    async function toggleLayer(layerId) {
        const layer = state.layers.find(l => l.id === layerId);
        if (!layer) return;

        const checkbox = document.getElementById(`layer-${layerId}`);
        const isChecked = checkbox.checked;

        if (isChecked) {
            await addLayerToMap(layer);
            Toast.show('Layer Added', `${layer.name} is now visible`, 'success');
        } else {
            removeLayerFromMap(layer);
            Toast.show('Layer Removed', `${layer.name} has been hidden`, 'info');
        }

        updateStats();
    }

    async function addLayerToMap(layer) {
        const layerData = {
            layer: layer,
            features: new L.FeatureGroup(),
            loadedBounds: null,
            loading: false
        };

        layerData.features.addTo(state.map);
        state.activeLayers[layer.id] = layerData;

        document.querySelector(`.layer-item[data-layer-id="${layer.id}"]`).classList.add('active');

        // Load features
        await loadLayerFeatures(layer.id);

        // Auto-zoom if features found
        if (layerData.features.getLayers().length > 0) {
            try {
                const bounds = layerData.features.getBounds();
                state.map.fitBounds(bounds, { padding: [50, 50], maxZoom: 16 });
            } catch (e) {
                console.log('Could not auto-zoom to layer');
            }
        }
    }

    function removeLayerFromMap(layer) {
        const layerData = state.activeLayers[layer.id];
        if (layerData) {
            state.map.removeLayer(layerData.features);
            delete state.activeLayers[layer.id];
            document.querySelector(`.layer-item[data-layer-id="${layer.id}"]`).classList.remove('active');
        }
        updateStats();
    }

    async function loadLayerFeatures(layerId) {
        const layerData = state.activeLayers[layerId];
        if (!layerData || layerData.loading) return;

        const bounds = state.map.getBounds();

        // Check if reload needed
        if (layerData.loadedBounds && layerData.loadedBounds.contains(bounds)) {
            return;
        }

        layerData.loading = true;
        const expanded = bounds.pad(CONFIG.FEATURE_LOAD_PAD);

        try {
            const params = new URLSearchParams({
                layer_id: layerId,
                minx: expanded.getWest(),
                miny: expanded.getSouth(),
                maxx: expanded.getEast(),
                maxy: expanded.getNorth()
            });

            const response = await fetch(`${CONFIG.URLS.LAYER_FEATURES}?${params}`);
            if (!response.ok) throw new Error('Failed to load features');

            const geojson = await response.json();

            // Clear and add new features
            layerData.features.clearLayers();

            if (geojson.features && geojson.features.length > 0) {
                const geoJsonLayer = L.geoJSON(geojson, {
                    style: getLayerStyle(layerData.layer),
                    pointToLayer: (feature, latlng) => {
                        return L.circleMarker(latlng, {
                            radius: 6,
                            fillColor: getLayerColor(layerData.layer.type),
                            color: '#fff',
                            weight: 2,
                            opacity: 1,
                            fillOpacity: 0.8
                        });
                    },
                    onEachFeature: (feature, leafletLayer) => {
                        const popupContent = createPopupContent(feature, layerData.layer, layerId);
                        leafletLayer.bindPopup(popupContent, {
                            maxWidth: 300,
                            className: 'custom-popup'
                        });
                    }
                });

                geoJsonLayer.eachLayer(l => layerData.features.addLayer(l));
                layerData.loadedBounds = expanded;

                updateFeatureCount(layerId, geojson.features.length);
            } else {
                updateFeatureCount(layerId, 0);
            }
        } catch (error) {
            console.error(`Error loading features for layer ${layerId}:`, error);
        } finally {
            layerData.loading = false;
        }
    }

    function createPopupContent(feature, layer, layerId) {
        const coords = feature.geometry.coordinates;
        let lat, lng;

        if (feature.geometry.type === 'Point') {
            [lng, lat] = coords;
        } else if (feature.geometry.type === 'LineString' && coords.length > 0) {
            [lng, lat] = coords[0];
        } else if (feature.geometry.type === 'Polygon' && coords[0] && coords[0].length > 0) {
            [lng, lat] = coords[0][0];
        }

        return `
            <div class="popup-content">
                <h4>${layer.name}</h4>
                <p><strong>Type:</strong> ${layer.type}</p>
                <p><strong>Server:</strong> ${layer.server_name}</p>
                ${lat && lng ? `<p><strong>Location:</strong> ${lat.toFixed(5)}, ${lng.toFixed(5)}</p>` : ''}
                <button class="popup-btn" onclick="gisApp.downloadAreaWithConfirm(${layerId}, ${lat || 0}, ${lng || 0}, '${layer.name}')">
                    💾 Download This Area
                </button>
            </div>
        `;
    }

    function updateAllLayerFeatures() {
        Object.keys(state.activeLayers).forEach(layerId => {
            loadLayerFeatures(layerId);
        });
    }

    function updateFeatureCount(layerId, count) {
        const countEl = document.getElementById(`count-${layerId}`);
        if (countEl) {
            countEl.textContent = count > 0 ? `${count} features` : '';
        }
    }

    async function handleMapClick(e) {
        state.clickedLocation = e.latlng;
        await showNearbyLayers(e.latlng.lat, e.latlng.lng);
    }

    async function showNearbyLayers(lat, lng) {
        const sidebar = document.getElementById('sidebar');
        const list = document.getElementById('nearbyList');

        sidebar.classList.add('active');
        list.innerHTML = '<div class="spinner"></div>';

        // Show location info
        const infoBox = document.createElement('div');
        infoBox.className = 'nearby-info-box';
        infoBox.innerHTML = `
            <strong>📍 Clicked Location</strong>
            <small>Lat: ${lat.toFixed(5)}, Lng: ${lng.toFixed(5)}</small>
        `;

        try {
            const params = new URLSearchParams({
                lat: lat,
                lng: lng,
                dist: CONFIG.SEARCH_RADIUS
            });

            const response = await fetch(`${CONFIG.URLS.NEARBY_LAYERS}?${params}`);
            const layers = await response.json();

            if (!layers.length) {
                list.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">🔍</div>
                        <div class="empty-state-title">No Layers Found</div>
                        <div class="empty-state-message">No layers with features within 2km of this location</div>
                    </div>
                `;
                return;
            }

            // Clear selection
            state.selectedNearbyLayers.clear();

            let html = '';
            layers.forEach(layer => {
                state.selectedNearbyLayers.add(layer.id);
                html += `
                    <div class="nearby-item">
                        <label>
                            <input type="checkbox" 
                                   value="${layer.id}" 
                                   checked
                                   onchange="gisApp.toggleNearbyLayer(${layer.id})">
                            <div class="nearby-item-info">
                                <div class="nearby-item-name">
                                    ${getTypeIcon(layer.type)} ${layer.name}
                                </div>
                                <div class="nearby-item-meta">
                                    <span class="distance-badge">${layer.distance_m}m away</span>
                                    <span>${layer.feature_count} features</span>
                                    <span>${layer.server_name}</span>
                                </div>
                            </div>
                        </label>
                    </div>
                `;
            });

            list.innerHTML = '';
            list.appendChild(infoBox);
            list.innerHTML += html;

            updateNearbyDownloadSummary();

        } catch (error) {
            console.error('Error loading nearby layers:', error);
            list.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">⚠</div>
                    <div class="empty-state-title">Error</div>
                    <div class="empty-state-message">Failed to load nearby layers</div>
                </div>
            `;
        }
    }

    function toggleNearbyLayer(layerId) {
        if (state.selectedNearbyLayers.has(layerId)) {
            state.selectedNearbyLayers.delete(layerId);
        } else {
            state.selectedNearbyLayers.add(layerId);
        }
        updateNearbyDownloadSummary();
    }

    function updateNearbyDownloadSummary() {
        const summaryEl = document.getElementById('downloadSummary');
        if (!summaryEl) return;

        const count = state.selectedNearbyLayers.size;
        const hasEnough = state.userConnects >= count;

        summaryEl.innerHTML = `
            <div class="summary-row">
                <span>Selected Layers:</span>
                <span>${count}</span>
            </div>
            <div class="summary-row">
                <span>Connect Cost:</span>
                <span class="${hasEnough ? 'cost-value success' : 'cost-value error'}">${count} connects</span>
            </div>
            <div class="summary-row">
                <span>Your Connects:</span>
                <span class="cost-value">${state.userConnects}</span>
            </div>
            <div class="summary-row">
                <span>After Download:</span>
                <span class="${hasEnough ? 'cost-value success' : 'cost-value error'}">
                    ${hasEnough ? state.userConnects - count : 'Insufficient'}
                </span>
            </div>
        `;

        const downloadBtn = document.querySelector('#nearbyForm button[type="submit"]');
        if (downloadBtn) {
            downloadBtn.disabled = !hasEnough || count === 0;
            if (!hasEnough) {
                downloadBtn.innerHTML = '<span>⚠</span><span>Insufficient Connects</span>';
            } else if (count === 0) {
                downloadBtn.innerHTML = '<span>💾</span><span>Select Layers to Download</span>';
            } else {
                downloadBtn.innerHTML = `<span>💾</span><span>Download ${count} Layer${count > 1 ? 's' : ''}</span>`;
            }
        }
    }

    async function downloadNearbyLayers(e) {
        e.preventDefault();

        const selectedCount = state.selectedNearbyLayers.size;
        if (selectedCount === 0) {
            Toast.show('No Selection', 'Please select at least one layer', 'warning');
            return;
        }

        // Show confirmation modal
        Modal.show({
            icon: '💾',
            title: 'Confirm Download',
            subtitle: 'Review your download details',
            body: `
                <div class="cost-info">
                    <div class="cost-row">
                        <span class="cost-label">Layers to Download:</span>
                        <span class="cost-value">${selectedCount}</span>
                    </div>
                    <div class="cost-row">
                        <span class="cost-label">Connect Cost:</span>
                        <span class="cost-value warning">${selectedCount} connects</span>
                    </div>
                    <div class="cost-row">
                        <span class="cost-label">Your Current Connects:</span>
                        <span class="cost-value">${state.userConnects}</span>
                    </div>
                    <div class="cost-row">
                        <span class="cost-label">Remaining After Download:</span>
                        <span class="cost-value ${state.userConnects - selectedCount >= 0 ? 'success' : 'error'}">
                            ${state.userConnects - selectedCount}
                        </span>
                    </div>
                </div>
                <div class="selected-layers-list">
                    <strong style="color: white; display: block; margin-bottom: 8px;">Selected Layers:</strong>
                    ${Array.from(state.selectedNearbyLayers).map(id => {
                        const layer = state.layers.find(l => l.id === parseInt(id));
                        return `<div class="selected-layer-item">${getTypeIcon(layer.type)} ${layer.name}</div>`;
                    }).join('')}
                </div>
            `,
            confirmText: 'Download Now',
            onConfirm: () => performDownload(),
            onCancel: () => {
                Toast.show('Cancelled', 'Download cancelled', 'info');
            }
        });
    }

    async function performDownload() {
        Progress.show('Downloading Layers...');
        Progress.update(20, 'Preparing download...');

        try {
            const formData = new FormData();
            Array.from(state.selectedNearbyLayers).forEach(id => {
                formData.append('layer_ids[]', id);
            });

            if (state.clickedLocation) {
                const { lat, lng } = state.clickedLocation;
                formData.append('lat', lat);
                formData.append('lng', lng);
                formData.append('minx', lng - CONFIG.MAX_DOWNLOAD_AREA);
                formData.append('miny', lat - CONFIG.MAX_DOWNLOAD_AREA);
                formData.append('maxx', lng + CONFIG.MAX_DOWNLOAD_AREA);
                formData.append('maxy', lat + CONFIG.MAX_DOWNLOAD_AREA);
            }

            Progress.update(40, 'Fetching features...');

            const response = await fetch(CONFIG.URLS.EXPORT_DXF, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-CSRFToken': getCSRFToken()
                },
                credentials: 'same-origin'
            });

            Progress.update(70, 'Processing data...');

            if (!response.ok) {
                const contentType = response.headers.get('content-type');
                if (contentType && contentType.includes('application/json')) {
                    const error = await response.json();
                    throw new Error(error.error || 'Download failed');
                } else {
                    throw new Error(`Server error: ${response.status}`);
                }
            }

            Progress.update(90, 'Preparing file...');

            const blob = await response.blob();
            downloadFile(blob, `export_${Date.now()}.dxf`);

            Progress.update(100, 'Complete!');

            // Update connects
            state.userConnects -= state.selectedNearbyLayers.size;
            updateConnectsDisplay();

            closeSidebar();
            Toast.show('Success!', 'Download completed successfully', 'success', 5000);

        } catch (error) {
            Toast.show('Download Failed', error.message, 'error');
        } finally {
            setTimeout(() => Progress.hide(), 1000);
        }
    }

    async function downloadAreaWithConfirm(layerId, lat, lng, layerName) {
        Modal.show({
            icon: '💾',
            title: 'Download Layer Area',
            subtitle: layerName,
            body: `
                <div class="cost-info">
                    <div class="cost-row">
                        <span class="cost-label">Layer:</span>
                        <span class="cost-value">${layerName}</span>
                    </div>
                    <div class="cost-row">
                        <span class="cost-label">Location:</span>
                        <span class="cost-value">${lat.toFixed(5)}, ${lng.toFixed(5)}</span>
                    </div>
                    <div class="cost-row">
                        <span class="cost-label">Area Size:</span>
                        <span class="cost-value">~100m × 100m</span>
                    </div>
                    <div class="cost-row">
                        <span class="cost-label">Connect Cost:</span>
                        <span class="cost-value warning">1 connect</span>
                    </div>
                    <div class="cost-row">
                        <span class="cost-label">Your Connects:</span>
                        <span class="cost-value ${state.userConnects >= 1 ? 'success' : 'error'}">
                            ${state.userConnects} ${state.userConnects >= 1 ? '✓' : '(Insufficient)'}
                        </span>
                    </div>
                </div>
            `,
            confirmText: 'Download',
            onConfirm: () => downloadSingleArea(layerId, lat, lng, layerName),
            onCancel: () => {}
        });
    }

    async function downloadSingleArea(layerId, lat, lng, layerName) {
        Progress.show(`Downloading ${layerName}...`);
        Progress.update(30, 'Fetching features...');

        try {
            const formData = new FormData();
            formData.append('layer_ids[]', layerId);
            formData.append('lat', lat);
            formData.append('lng', lng);
            formData.append('minx', lng - CONFIG.MAX_DOWNLOAD_AREA);
            formData.append('miny', lat - CONFIG.MAX_DOWNLOAD_AREA);
            formData.append('maxx', lng + CONFIG.MAX_DOWNLOAD_AREA);
            formData.append('maxy', lat + CONFIG.MAX_DOWNLOAD_AREA);

            Progress.update(60, 'Processing...');

            const response = await fetch(CONFIG.URLS.EXPORT_DXF, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-CSRFToken': getCSRFToken()
                },
                credentials: 'same-origin'
            });

            if (!response.ok) {
                throw new Error('Download failed');
            }

            Progress.update(90, 'Preparing file...');

            const blob = await response.blob();
            downloadFile(blob, `${layerName}_${Date.now()}.dxf`);

            Progress.update(100, 'Complete!');

            // Update connects
            state.userConnects--;
            updateConnectsDisplay();

            Toast.show('Success!', `${layerName} downloaded successfully`, 'success');

        } catch (error) {
            Toast.show('Download Failed', error.message, 'error');
        } finally {
            setTimeout(() => Progress.hide(), 1000);
        }
    }

    function downloadFile(blob, filename) {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    function closeSidebar() {
        document.getElementById('sidebar').classList.remove('active');
    }

    function toggleMinimize() {
        const panel = document.getElementById('layerPanel');
        const icon = document.getElementById('minimizeIcon');

        panel.classList.toggle('minimized');
        icon.textContent = panel.classList.contains('minimized') ? '+' : '−';
    }

    function updateStats() {
        const activeCount = Object.keys(state.activeLayers).length;
        document.getElementById('layerCount').textContent =
            activeCount > 0 ? `(${activeCount} active)` : '';
    }

    function zoomToLayer(layerId) {
        const layer = state.layers.find(l => l.id === layerId);
        if (!layer) return;

        if (!state.activeLayers[layerId]) {
            document.getElementById(`layer-${layerId}`).click();
        } else if (layer.centroid_lat && layer.centroid_lng) {
            state.map.flyTo([layer.centroid_lat, layer.centroid_lng], 15);
            Toast.show('Zoomed', `Moved to ${layer.name}`, 'info');
        }
    }

    function refreshLayers() {
        document.getElementById('layerList').innerHTML = '<div class="spinner"></div>';
        loadLayers().then(() => {
            Toast.show('Refreshed', 'Layer list updated', 'success');
        });
    }

    function debounce(func, wait) {
        let timeout;
        return function(...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    function getTypeIcon(type) {
        return { point: '📍', polyline: '📈', polygon: '🗺️' }[type] || '📄';
    }

    function getLayerStyle(layer) {
        const styles = {
            polygon: { color: '#3388ff', weight: 2, opacity: 0.8, fillOpacity: 0.3 },
            polyline: { color: '#ff7800', weight: 3, opacity: 0.8 },
            point: { color: '#51bbd6', weight: 2, opacity: 0.8 }
        };
        return styles[layer.type] || styles.polygon;
    }

    function getLayerColor(type) {
        return { point: '#e74c3c', polyline: '#f39c12', polygon: '#3498db' }[type] || '#95a5a6';
    }

    function switchBasemap(name) {
        if (state.basemaps[state.currentBasemap]) {
            state.map.removeLayer(state.basemaps[state.currentBasemap]);
        }
        state.currentBasemap = name;
        if (state.basemaps[name]) {
            state.basemaps[name].addTo(state.map);
        }
    }

    function bindEvents() {
        // Basemap switcher
        document.querySelectorAll('input[name="basemap"]').forEach(radio => {
            radio.addEventListener('change', (e) => {
                if (e.target.checked) {
                    switchBasemap(e.target.value);
                }
            });
        });

        // Nearby form submission
        const nearbyForm = document.getElementById('nearbyForm');
        if (nearbyForm) {
            nearbyForm.addEventListener('submit', downloadNearbyLayers);
        }

        // Basemap control hover
        const basemapControl = document.querySelector('.basemap-control');
        if (basemapControl) {
            basemapControl.addEventListener('mouseenter', () => {
                document.querySelector('.basemap-options').classList.add('active');
            });
            basemapControl.addEventListener('mouseleave', () => {
                document.querySelector('.basemap-options').classList.remove('active');
            });
        }
    }

    // Public API
    window.gisApp = {
        init,
        toggleLayer,
        zoomToLayer,
        refreshLayers,
        closeSidebar,
        toggleMinimize,
        downloadAreaWithConfirm,
        toggleNearbyLayer
    };

})();