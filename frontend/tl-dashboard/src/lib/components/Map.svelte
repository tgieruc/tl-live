<script lang="ts">
	import { onMount } from 'svelte';
	import maplibregl from 'maplibre-gl';
	import 'maplibre-gl/dist/maplibre-gl.css';
	import { LINE_COLORS, getLineColor, getRouteTypeStyle } from '$lib/types';
	import { stopId, stopCoords, stopName } from '$lib/stores/stop';
	import { activeLines } from '$lib/stores/activeLines';
	import { base } from '$app/paths';

	const DEFAULT_CENTER: [number, number] = [6.583961, 46.532379];

	let mapContainer: HTMLDivElement;
	let map: maplibregl.Map;

	// Route geometries with pre-computed cumulative distances
	type RouteGeom = {
		coords: [number, number][];
		cumDists: number[];
		totalDist: number;
	};
	// Keyed by route_key (e.g. "25_Pully, gare") AND by line number
	let routeGeomsByKey: Record<string, RouteGeom> = {};
	let routeGeoms: Record<string, RouteGeom[]> = {};

	// Trajectory data from backend
	type Waypoint = { d: number; t: number };
	type Trajectory = {
		line: string;
		destination: string;
		route_key: string;
		waypoints: Waypoint[];
	};
	let trajectories: Trajectory[] = [];
	let animFrameId: number | null = null;

	function computeCumDists(coords: [number, number][]): number[] {
		const dists = [0];
		for (let i = 1; i < coords.length; i++) {
			const dx = coords[i][0] - coords[i - 1][0];
			const dy = coords[i][1] - coords[i - 1][1];
			dists.push(dists[i - 1] + Math.sqrt(dx * dx + dy * dy));
		}
		return dists;
	}

	function pointAtFraction(frac: number, geom: RouteGeom): [number, number] {
		const targetDist = frac * geom.totalDist;
		if (targetDist <= 0) return geom.coords[0];
		if (targetDist >= geom.totalDist) return geom.coords[geom.coords.length - 1];

		for (let i = 0; i < geom.cumDists.length - 1; i++) {
			if (geom.cumDists[i + 1] >= targetDist) {
				const segLen = geom.cumDists[i + 1] - geom.cumDists[i];
				const t = segLen === 0 ? 0 : (targetDist - geom.cumDists[i]) / segLen;
				return [
					geom.coords[i][0] + t * (geom.coords[i + 1][0] - geom.coords[i][0]),
					geom.coords[i][1] + t * (geom.coords[i + 1][1] - geom.coords[i][1])
				];
			}
		}
		return geom.coords[geom.coords.length - 1];
	}

	/** Get bus position along route at a given fraction (0..1) */
	function busPositionOnRoute(d: number, routeKey: string): [number, number] | null {
		// Direct match by route_key
		const geom = routeGeomsByKey[routeKey];
		if (geom) return pointAtFraction(d, geom);

		// Fallback: use longest geometry for this line
		const line = routeKey.split('_')[0];
		const geoms = routeGeoms[line];
		if (!geoms || geoms.length === 0) return null;
		let best = geoms[0];
		for (const g of geoms) {
			if (g.totalDist > best.totalDist) best = g;
		}
		return pointAtFraction(d, best);
	}

	/** Interpolate d value from waypoints based on current time */
	function getDAtTime(waypoints: Waypoint[], nowSec: number): number | null {
		if (waypoints.length === 0) return null;

		// Before first waypoint
		if (nowSec < waypoints[0].t) return null;
		// After last waypoint
		if (nowSec > waypoints[waypoints.length - 1].t) return null;

		for (let i = 0; i < waypoints.length - 1; i++) {
			if (nowSec >= waypoints[i].t && nowSec <= waypoints[i + 1].t) {
				const dt = waypoints[i + 1].t - waypoints[i].t;
				const frac = dt === 0 ? 0 : (nowSec - waypoints[i].t) / dt;
				return waypoints[i].d + frac * (waypoints[i + 1].d - waypoints[i].d);
			}
		}
		return null;
	}

	async function loadRoutes(m: maplibregl.Map) {
		let routes, stops;
		try {
			const [routesRes, stopsRes] = await Promise.all([fetch(`${base}/api/routes`), fetch(`${base}/api/stops`)]);
			if (!routesRes.ok || !stopsRes.ok) {
				console.error('Failed to load routes/stops:', routesRes.status, stopsRes.status);
				return;
			}
			routes = await routesRes.json();
			stops = await stopsRes.json();
		} catch (e) {
			console.error('Failed to load routes/stops:', e);
			return;
		}

		// Pre-compute route geometries with cumulative distances
		for (const feat of routes.features) {
			const line = feat.properties.line;
			const headsign = feat.properties.headsign;
			const routeKey = `${line}_${headsign}`;
			const coords = feat.geometry.coordinates;
			const cumDists = computeCumDists(coords);
			const geom = { coords, cumDists, totalDist: cumDists[cumDists.length - 1] };

			routeGeomsByKey[routeKey] = geom;
			if (!routeGeoms[line]) routeGeoms[line] = [];
			routeGeoms[line].push(geom);
		}

		// Fill in colors using our LINE_COLORS map for all features
		for (const feat of routes.features) {
			feat.properties.color = getLineColor(feat.properties.line);
		}

		m.addSource('routes', { type: 'geojson', data: routes });

		// Route lines — only shown for lines serving the selected stop
		m.addLayer({
			id: 'routes-glow',
			type: 'line',
			source: 'routes',
			filter: ['in', ['get', 'line'], ['literal', []]],
			layout: { 'line-join': 'round', 'line-cap': 'round' },
			paint: {
				'line-color': ['get', 'color'],
				'line-width': 6,
				'line-opacity': 0.12,
				'line-blur': 3
			}
		});
		m.addLayer({
			id: 'routes-line',
			type: 'line',
			source: 'routes',
			filter: ['in', ['get', 'line'], ['literal', []]],
			layout: { 'line-join': 'round', 'line-cap': 'round' },
			paint: {
				'line-color': ['get', 'color'],
				'line-width': 2.5,
				'line-opacity': 0.6
			}
		});

		m.addSource('stops', { type: 'geojson', data: stops });
		m.addLayer({
			id: 'stops-dot',
			type: 'circle',
			source: 'stops',
			paint: {
				'circle-color': '#ffffff',
				'circle-radius': 2.5,
				'circle-stroke-width': 1,
				'circle-stroke-color': '#0a0a0a',
				'circle-opacity': 0.5
			}
		});
		m.addLayer({
			id: 'stops-label',
			type: 'symbol',
			source: 'stops',
			minzoom: 15.5,
			layout: {
				'text-field': ['get', 'name'],
				'text-size': 10,
				'text-offset': [0, 1.2],
				'text-anchor': 'top',
				'text-font': ['Noto Sans Regular'],
				'text-max-width': 8
			},
			paint: { 'text-color': '#666666', 'text-halo-color': '#0a0a0a', 'text-halo-width': 1.5 }
		});
	}

	async function fetchTrajectories() {
		try {
			const res = await fetch(`${base}/api/positions?stop=${$stopId}`);
			if (!res.ok) return;
			const data = await res.json();
			trajectories = data.trajectories || [];
		} catch (e) {
			console.error('Failed to fetch trajectories', e);
		}
	}

	function animateBuses(m: maplibregl.Map) {
		function frame() {
			const nowSec = Date.now() / 1000;

			const features: any[] = [];

			for (const traj of trajectories) {
				const d = getDAtTime(traj.waypoints, nowSec);
				if (d === null) continue;

				const pos = busPositionOnRoute(d, traj.route_key);
				if (!pos) continue;

				features.push({
					type: 'Feature',
					geometry: { type: 'Point', coordinates: pos },
					properties: {
						line: traj.line,
						destination: traj.destination,
						color: getLineColor(traj.line)
					}
				});
			}

			const source = m.getSource('buses') as maplibregl.GeoJSONSource;
			if (source) {
				source.setData({ type: 'FeatureCollection', features });
			}

			animFrameId = requestAnimationFrame(frame);
		}

		frame();
	}

	let unsubActiveLines: (() => void) | null = null;

	onMount(() => {
		map = new maplibregl.Map({
			container: mapContainer,
			style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
			center: DEFAULT_CENTER,
			zoom: 14.5,
			attributionControl: false
		});

		map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
		map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');

		map.on('load', async () => {
			await loadRoutes(map);

			// Home stop marker
			map.addSource('home-stop', {
				type: 'geojson',
				data: {
					type: 'FeatureCollection',
					features: [
						{
							type: 'Feature',
							geometry: { type: 'Point', coordinates: $stopCoords },
							properties: { name: $stopName }
						}
					]
				}
			});
			map.addLayer({
				id: 'home-stop-glow',
				type: 'circle',
				source: 'home-stop',
				paint: { 'circle-color': '#00d4aa', 'circle-radius': 16, 'circle-opacity': 0.15, 'circle-blur': 1 }
			});
			map.addLayer({
				id: 'home-stop-dot',
				type: 'circle',
				source: 'home-stop',
				paint: {
					'circle-color': '#00d4aa',
					'circle-radius': 5,
					'circle-stroke-width': 2,
					'circle-stroke-color': '#0a0a0a'
				}
			});
			map.addLayer({
				id: 'home-stop-label',
				type: 'symbol',
				source: 'home-stop',
				layout: {
					'text-field': ['get', 'name'],
					'text-size': 11,
					'text-offset': [0, 1.5],
					'text-anchor': 'top',
					'text-font': ['Noto Sans Regular']
				},
				paint: { 'text-color': '#00d4aa', 'text-halo-color': '#0a0a0a', 'text-halo-width': 2 }
			});

			// Bus positions source (data-driven: works for any line)
			map.addSource('buses', {
				type: 'geojson',
				data: { type: 'FeatureCollection', features: [] }
			});

			map.addLayer({
				id: 'bus-glow',
				type: 'circle',
				source: 'buses',
				paint: {
					'circle-color': ['get', 'color'],
					'circle-radius': 12,
					'circle-opacity': 0.3,
					'circle-blur': 0.8
				}
			});
			map.addLayer({
				id: 'bus-dot',
				type: 'circle',
				source: 'buses',
				paint: {
					'circle-color': ['get', 'color'],
					'circle-radius': 6,
					'circle-stroke-width': 2,
					'circle-stroke-color': '#0a0a0a'
				}
			});
			map.addLayer({
				id: 'bus-label',
				type: 'symbol',
				source: 'buses',
				layout: {
					'text-field': ['get', 'line'],
					'text-size': 8,
					'text-font': ['Noto Sans Regular'],
					'text-allow-overlap': true
				},
				paint: { 'text-color': '#ffffff' }
			});

			// Fetch initial data and start animation
			await fetchTrajectories();
			animateBuses(map);

			// React to active lines changes — show only routes for the selected stop
			unsubActiveLines = activeLines.subscribe((lines) => {
				if (!map || !map.getLayer('routes-line')) return;
				const lineArray = Array.from(lines);
				const filter: any = lineArray.length > 0
					? ['in', ['get', 'line'], ['literal', lineArray]]
					: ['in', ['get', 'line'], ['literal', []]];
				map.setFilter('routes-line', filter);
				map.setFilter('routes-glow', filter);
			});
		});

		// Refresh trajectory data every 30 seconds
		const trajectoryInterval = setInterval(fetchTrajectories, 30_000);

		// React to stop changes
		const unsubCoords = stopCoords.subscribe((coords) => {
			if (!map) return;
			map.flyTo({ center: coords as [number, number], zoom: 14.5, duration: 1500 });
			const src = map.getSource('home-stop') as maplibregl.GeoJSONSource;
			if (src) {
				src.setData({
					type: 'FeatureCollection',
					features: [
						{
							type: 'Feature',
							geometry: { type: 'Point', coordinates: coords },
							properties: { name: $stopName }
						}
					]
				});
			}
		});

		const unsubStop = stopId.subscribe(() => {
			fetchTrajectories();
		});

		return () => {
			clearInterval(trajectoryInterval);
			if (animFrameId) cancelAnimationFrame(animFrameId);
			if (unsubActiveLines) unsubActiveLines();
			unsubCoords();
			unsubStop();
			map.remove();
		};
	});
</script>

<div bind:this={mapContainer} class="absolute inset-0 w-full h-full"></div>

<style>
	:global(.maplibregl-ctrl-group) {
		border-radius: 0 !important;
		box-shadow: 0 0 8px rgba(0, 212, 170, 0.15) !important;
		border: 1px solid #333 !important;
		background: #0a0a0a !important;
	}
	:global(.maplibregl-ctrl-group button) {
		width: 32px !important;
		height: 32px !important;
		background-color: #0a0a0a !important;
		border-bottom-color: #333 !important;
	}
	:global(.maplibregl-ctrl-group button:hover) {
		background-color: #1a1a1a !important;
	}
	:global(.maplibregl-ctrl-group button .maplibregl-ctrl-icon) {
		filter: invert(1) !important;
	}
	:global(.maplibregl-ctrl-attrib) {
		font-size: 10px !important;
		font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace !important;
		background: rgba(0, 0, 0, 0.8) !important;
		color: #666 !important;
	}
	:global(.maplibregl-ctrl-attrib a) {
		color: #666 !important;
	}
</style>
