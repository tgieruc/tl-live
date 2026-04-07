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
	'25': '#e74c3c',
	'32': '#3498db',
	'33': '#f39c12'
};

export function getLineColor(line: string): string {
	return LINE_COLORS[line] ?? '#888888';
}
