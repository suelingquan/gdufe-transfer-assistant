export interface Course {
  code: string
  name: string
  credits: number
  category: string
  group: string
  semester: number | null
  score?: string | null
  passed?: boolean
}

export interface Program {
  major: string
  grade: number
  college: string
  total_credits: number
  required_credits: number
  courses: Course[]
  source: 'demo' | 'live' | 'import'
  updated_at: string
}

export interface ProgramSummary {
  major: string
  grade: number
  college: string
  total_credits: number
  required_credits: number
  course_count: number
  source: string
  updated_at: string
}

export interface StudentProfile {
  student_id: string
  name: string
  major: string
  grade: number
  college: string
  gpa: number
  completed: Course[]
}

export interface GpaEstimate {
  major: string
  count: number
  min: number
  median: number
  max: number
  percentile: number
  rank: number
  gap_to_min: number
  level: string
}

export interface Rule {
  id: string
  from_code: string
  from_name: string
  to_code: string
  to_name: string
  reason: string
  max_credits: number | null
}

export interface MatchInfo {
  target: Course
  completed: Course
  via: 'code' | 'name' | 'rule' | 'fuzzy'
  rule: Rule | null
}

export interface ComparisonResult {
  major: string
  grade: number
  total_credits: number
  required_credits: number
  earned_credits: number
  overlap_count: number
  satisfied_count: number
  missing_count: number
  missing_credits: number
  credit_gap: number
  transferable_credits: number
  overlap_courses: Course[]
  missing_courses: Course[]
  satisfied: MatchInfo[]
  substitutions: MatchInfo[]
}

export interface CompareResponse {
  profile: StudentProfile
  current: Program
  results: ComparisonResult[]
  ranking: ComparisonResult[]
  fetch_errors?: string[]
}
