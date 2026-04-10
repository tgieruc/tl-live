export interface Departure {
	stop_name: string;
	stop_id: string;
	line: string;
	destination: string;
	departure: string;
	delay: number | null;
}

export interface DeparturesResponse {
	departures: Departure[];
}

export const LINE_COLORS: Record<string, string> = {
	// TL Bus lines
	'1': '#2ecc71',
	'2': '#9b59b6',
	'3': '#1abc9c',
	'4': '#e67e22',
	'6': '#27ae60',
	'7': '#8e44ad',
	'8': '#2980b9',
	'9': '#c0392b',
	'12': '#16a085',
	'17': '#d35400',
	'18': '#f1c40f',
	'21': '#e74c3c',
	'22': '#3498db',
	'24': '#e67e22',
	'25': '#e74c3c',
	'32': '#3498db',
	'33': '#f39c12',
	'45': '#1abc9c',
	'46': '#9b59b6',
	'47': '#2ecc71',
	'54': '#c0392b',
	'60': '#d35400',
	'85': '#16a085',
	// Metro
	M1: '#e74c3c',
	M2: '#f39c12',
	// Night buses
	N1: '#6c5ce7',
	N2: '#a29bfe',
	N3: '#74b9ff',
	N4: '#55efc4',
	N5: '#ffeaa7',
	N6: '#fab1a0',
	// S-Bahn
	S1: '#2980b9',
	S2: '#27ae60',
	S3: '#e67e22',
	S4: '#8e44ad',
	S11: '#3498db',
	S21: '#2ecc71',
	S31: '#e74c3c',
	// Regional/Intercity
	IR: '#e74c3c',
	RE: '#2ecc71',
	IC: '#e74c3c',
	ICE: '#c0392b',
	S: '#3498db',
};

/** Maplibre line-dasharray values by GTFS route_type */
export const ROUTE_TYPE_STYLES: Record<number, { dasharray: number[] | null; width: number }> = {
	0: { dasharray: null, width: 3 },      // Tram: solid, slightly thicker
	1: { dasharray: null, width: 3.5 },     // Metro: solid, thicker
	2: { dasharray: [2, 1.5], width: 2.5 }, // Rail: dashed
	3: { dasharray: null, width: 2.5 },     // Bus: solid (default)
};

export function getRouteTypeStyle(routeType: number): { dasharray: number[] | null; width: number } {
	return ROUTE_TYPE_STYLES[routeType] ?? ROUTE_TYPE_STYLES[3];
}

function hashColor(str: string): string {
	let hash = 0;
	for (let i = 0; i < str.length; i++) {
		hash = str.charCodeAt(i) + ((hash << 5) - hash);
	}
	const h = ((hash % 360) + 360) % 360;
	return `hsl(${h}, 65%, 55%)`;
}

export function getLineColor(line: string): string {
	return LINE_COLORS[line] ?? hashColor(line);
}
