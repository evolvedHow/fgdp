export interface ElectionOption {
  year: number;
  election_type: string;
  office: string;
  label: string;
}

export interface DistrictResult {
  id: string;
  district_num: number;
  dem_2pv: number;
  total_vap: number;
  centroid_lat: number;
  centroid_lon: number;
}

export interface VtdDetail {
  dem_2pv: number;
  total_vap: number;
}

export interface MapMeta {
  id: string;
  label: string;
  n_districts: number;
  created: string;
}

export interface Histogram {
  edges: number[];
  counts: number[];
  enacted: number | null;
  p5: number;
  p50: number;
  p95: number;
  mean: number;
}

export interface MetricGrade {
  label: string;
  headline: string;
  category: string;
  description: string;
  takeaway: string;
  grade: string;
  enacted: number;
  pct_rank: number;
  histogram: Histogram;
}

export interface CompositeGrade {
  label: string;
  grade: string;
  description: string;
  ensemble_pass?: boolean;
  normative_pass?: boolean;
}

export type Grades = Record<string, MetricGrade | CompositeGrade>;

export interface ScoredPlan {
  id: string;
  label: string;
  source: 'catalog' | 'upload' | 'library';
  run_id: string;
  map_id?: string;
  metrics: Record<string, { value: number; pct_rank: number; grade: string }>;
  grades: Grades;
  districts: DistrictResult[];
  vtd_assignments?: Record<string, number>;
  vtd_details?: Record<string, VtdDetail>;
}

export interface RunMeta {
  id: string;
  name: string;
  algorithm: string;
  date: string;
  n_plans: number;
  description: string;
  tags: string[];
  source?: string;       // 'gerrychain' | 'alarm' | undefined for legacy runs
  chamber?: string;      // 'congress' | 'senate' | 'house'
  elections?: ElectionOption[];  // populated for GerryChain scorecard runs
  election_idx?: number;
  plans?: ScoredPlan[];  // plans with full district data
}

export interface Summary {
  state: string;
  state_full: string;
  plan_type: string;
  plan_year: string;
  n_districts: number;
  n_plans: number;
  enacted_label: string;
  story_html?: string | null;
  run: RunMeta;
}

export interface RiverData {
  n_sample: number;
  n_districts: number;
  p5: number[];
  p50: number[];
  p95: number[];
  enacted?: number[] | null;
  enacted_district_ids?: number[] | null;
}

export interface Analysis {
  summary: Summary;
  grades: Grades;
  river: RiverData | null;
}
