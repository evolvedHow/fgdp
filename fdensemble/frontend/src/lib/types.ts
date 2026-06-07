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
  // Optional demographics (present when scored via /api/score-map)
  // Primary source: bvap_* columns in vtd_composite.parquet (Census PL 94-171 P4)
  total_pop?:      number;
  vap_black?:      number;
  vap_hisp?:       number;
  vap_white?:      number;
  vap_aian?:       number;
  vap_asian?:      number;
  vap_coalition?:  number;  // all non-white VAP (bvap_coalition)
  pct_black?:      number;
  pct_hisp?:       number;
  pct_white?:      number;
  pct_aian?:       number;
  pct_asian?:      number;
  pct_minority?:   number;  // 1 - pct_white (non-white VAP share = minority coalition %)
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
  p25: number;
  p40: number;
  p50: number;
  p60: number;
  p75: number;
  p95: number;
  mean: number;
}

export interface FormulaInfo {
  formula: string;
  detail: string;
  data_source: string;
  config_keys: string[];
  grading_method?: string;
}

export interface MetricGrade {
  label: string;
  headline: string;
  category: string;
  description: string;
  takeaway: string;
  grade: string;
  grade_symmetric?: string;  // retained for VRA floor metrics (lineage)
  floor?: number;            // 10th-pct floor value for floor-graded metrics
  enacted: number;
  pct_rank: number;
  histogram: Histogram;
  a_grade_range?: { lo: number | null; hi: number | null };
  formula_info?: FormulaInfo;
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

export interface ScatterPair {
  x: number[];
  y: number[];
  enacted_x: number | null;
  enacted_y: number | null;
  r: number | null;
}

export interface CorrelationData {
  available: boolean;
  matrix?: Record<string, Record<string, number | null>>;
  scatter?: Record<string, ScatterPair>;
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

export interface ProportionalityGap {
  /** VAP-weighted statewide composite Dem two-party vote share (e.g. 0.482) */
  statewide_dem_2pv:   number;
  /** statewide_dem_2pv × n_districts — what proportional representation would deliver */
  proportional_target: number;
  /** Neutral ensemble median dem_seats (p50 of histogram) */
  ensemble_median:     number;
  ensemble_p5:         number;
  ensemble_p95:        number;
  /** Enacted map dem_seats value */
  enacted_seats:       number;
  /** ensemble_median − proportional_target (negative = neutral maps fall short of proportionality) */
  structural_gap:      number;
  /** enacted_seats − ensemble_median (negative = enacted below neutral) */
  manipulation_gap:    number;
  /** enacted_seats − proportional_target (full gap from strict proportionality) */
  total_gap:           number;
  n_districts:         number;
  elections_used:      string[];
}

export interface BenchmarkConfig {
  competitive_threshold: number;
  majority_threshold: number;
  bvap_majority_threshold: number;
  influence_min_threshold: number;
  influence_max_threshold: number;
  grading: {
    ensemble_pass_lo: number;
    ensemble_pass_hi: number;
    floor_grade_floor_pct: number;
    floor_grade_a_pct: number;
    seats_grade_a_pct: number;
    seats_grade_b_pct: number;
    comp_grade_a_pct: number;
    symmetric_a_band: number;
    symmetric_b_band: number;
    directional_a_pct: number;
    directional_b_pct: number;
  };
  source_locations: Record<string, string>;
}

export interface Analysis {
  summary: Summary;
  grades: Grades;
  river: RiverData | null;
  proportionality?: ProportionalityGap | null;
  config?: BenchmarkConfig | null;
}
