export interface ElectionOption {
  year: number;
  election_type: string;
  office: string;
  label: string;
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
  category: string;
  description: string;
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

export interface Summary {
  state: string;
  state_full: string;
  plan_type: string;
  plan_year: string;
  n_districts: number;
  n_plans: number;
  enacted_label: string;
  run: RunMeta;
}

export interface RiverData {
  n_sample: number;
  n_districts: number;
  p5: number[];
  p50: number[];
  p95: number[];
  enacted?: number[] | null;  // present for GerryChain scorecard runs
}

export interface Analysis {
  summary: Summary;
  grades: Grades;
  river: RiverData | null;
}
