import { useCallback, useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { api } from './api'
import type {
  ComparisonResult,
  Course,
  GpaEstimate,
  MatchInfo,
  Program,
  ProgramSummary,
  Rule,
  StudentProfile,
} from './types'
import './index.css'

type Tab = 'overview' | 'missing' | 'substitution' | 'ranking' | 'gpa' | 'source'
const PROFILE_KEY = 'gdufe_transfer_profile'

// Strip any leftover HTML markup / entities that may slip through scraping.
const cleanName = (value: string): string =>
  (value || '')
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&')
    .trim()

function Stat({ label, value, hint, tone }: {
  label: string; value: string | number; hint?: string; tone?: 'good' | 'warn' | 'info'
}) {
  return (
    <div className={`stat stat-${tone || 'info'}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  )
}

function CourseTable({ courses, empty }: { courses: Course[]; empty: string }) {
  if (!courses.length) return <p className="empty">{empty}</p>
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>课程名称</th><th>课程代码</th><th>学分</th><th>性质</th><th>模块</th><th>学期</th>
          </tr>
        </thead>
        <tbody>
          {courses.map((course, i) => (
            <tr key={`${course.code}-${course.name}-${i}`}>
              <td className="strong">{course.name}</td>
              <td>{course.code || '—'}</td>
              <td>{course.credits}</td>
              <td>{course.category || '—'}</td>
              <td>{course.group || '—'}</td>
              <td>{course.semester ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SubstitutionTable({ items }: { items: MatchInfo[] }) {
  if (!items.length) return <p className="empty">未发现可替代课程。可在下方查看/贡献替代规则。</p>
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr><th>已修课程</th><th>可替代目标课程</th><th>学分</th><th>依据</th><th>说明</th></tr>
        </thead>
        <tbody>
          {items.map((item, i) => (
            <tr key={`${item.completed.name}-${item.target.name}-${i}`}>
              <td className="strong">{item.completed.name}</td>
              <td>{item.target.name}</td>
              <td>{item.target.credits}</td>
              <td><span className={`badge ${item.via === 'fuzzy' ? 'badge-warn' : 'badge-good'}`}>
                {item.via === 'rule' ? '替代规则' : item.via === 'fuzzy' ? '名称近似' : item.via === 'code' ? '课程代码' : '课程名称'}
              </span></td>
              <td className="muted">{item.rule?.reason || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function App() {
  const [programs, setPrograms] = useState<ProgramSummary[]>([])
  const [rules, setRules] = useState<Rule[]>([])
  // Login state: token drives everything. No token -> login screen.
  const [token, setToken] = useState(api.getStoredToken())
  const [profile, setProfile] = useState<StudentProfile | null>(null)
  const [options, setOptions] = useState<Record<string, string[] | [string, string[]][]>>({})
  const [collegesData, setCollegesData] = useState<{ value: string; label: string }[]>([])
  const [collegeMajorsMap, setCollegeMajorsMap] = useState<Record<string, string[]>>({})
  // Major name -> college form value, gathered during the cascade.
  const [majorColleges, setMajorColleges] = useState<Record<string, string>>({})
  const [captchaId, setCaptchaId] = useState('')
  const [captchaImage, setCaptchaImage] = useState('')
  const [credentials, setCredentials] = useState({ username: '', password: '', captcha: '' })

  const [grade, setGrade] = useState(new Date().getFullYear())
  const [currentMajor, setCurrentMajor] = useState('')
  const [gpa, setGpa] = useState(3.8)
  const [progressSemester, setProgressSemester] = useState(4)
  const [targetCollege, setTargetCollege] = useState('')
  const [targetMajors, setTargetMajors] = useState<string[]>([])
  const [gpaResults, setGpaResults] = useState<GpaEstimate[]>([])
  const [gpaTargets, setGpaTargets] = useState<string[]>([])
  const [stats, setStats] = useState<{
    title: string; year: number; note: string
    summary: Record<string, { count: number; min: number; p25: number; median: number; p75: number; max: number }>
  } | null>(null)
  const [result, setResult] = useState<{ profile: StudentProfile; current: Program; results: ComparisonResult[]; ranking: ComparisonResult[]; fetch_errors?: string[] } | null>(null)
  const [tab, setTab] = useState<Tab>('overview')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  // Demo programs are only a fallback for the public (not logged in) preview.
  const demoMajors = useMemo(
    () => Array.from(new Set(programs.filter((p) => p.grade === grade).map((p) => p.major))),
    [programs, grade],
  )

  // Flat major dropdown on the school's page. It is often empty until a
  // college is selected, so majors mainly come from the college cascade below.
  const optionMajors = useMemo(() => {
    for (const [name, values] of Object.entries(options)) {
      if (name.includes('专业') || name.toLowerCase().includes('zy') || name.toLowerCase().includes('major')) {
        return (Array.isArray(values) ? values : [])
          .filter((v): v is string => typeof v === 'string' && !v.includes('请选择'))
      }
    }
    return []
  }, [options])
  const optionGrades = useMemo(() => {
    for (const [name, values] of Object.entries(options)) {
      if (name.includes('年级') || name.includes('入学') || name.toLowerCase().includes('nj') || name.toLowerCase().includes('grade')) {
        return (values as string[]).filter((v) => /20\d{2}/.test(v))
      }
    }
    return []
  }, [options])

  // Real colleges come from the school's xsxy dropdown; demo grouping is a
  // fallback so the UI still works if that dropdown cannot be read.
  const colleges = useMemo<{ value: string; label: string }[]>(() => {
    if (collegesData.length) return collegesData
    const seen = new Map<string, string>()
    for (const p of programs) if (p.grade === grade) seen.set(p.college, p.college)
    return Array.from(seen.values()).map((c) => ({ value: c, label: c }))
  }, [collegesData, programs, grade])

  const grades = useMemo(() => {
    if (optionGrades.length) {
      return Array.from(new Set(optionGrades.map((v) => Number(v.match(/20\d{2}/)?.[0] || 0)).filter(Boolean))).sort((a, b) => b - a)
    }
    const current = new Date().getFullYear()
    return Array.from(new Set([...Array.from({ length: 6 }, (_, i) => current - i), ...programs.map((p) => p.grade)])).sort((a, b) => b - a)
  }, [optionGrades, programs])

  // Majors for the selected target college, loaded on demand from the school.
  const collegeMajors = useMemo(() => {
    if (!targetCollege) return optionMajors
    return collegeMajorsMap[targetCollege] || []
  }, [targetCollege, collegeMajorsMap, optionMajors])

  // Every major seen so far, grouped for the "my major" selector.
  const collegeGroups = useMemo<[string, string[]][]>(() => {
    const map = new Map<string, string[]>()
    for (const [value, list] of Object.entries(collegeMajorsMap)) {
      const label = colleges.find((c) => c.value === value)?.label || value
      map.set(label, list)
    }
    const auto = cleanName(profile?.major || currentMajor)
    if (auto && !Array.from(map.values()).some((list) => list.includes(auto))) {
      map.set('已匹配专业', [auto])
    }
    return Array.from(map.entries()).filter(([, list]) => list.length > 0)
  }, [colleges, collegeMajorsMap, profile, currentMajor])

  const majors = useMemo(() => {
    const set = new Set<string>(optionMajors)
    for (const list of Object.values(collegeMajorsMap)) list.forEach((m) => set.add(m))
    const auto = cleanName(profile?.major || currentMajor)
    if (auto) set.add(auto)
    return Array.from(set)
  }, [optionMajors, collegeMajorsMap, profile, currentMajor])

  const primary = result?.results[0] || null
  const best = result?.ranking[0] || null

  const refreshCaptcha = useCallback(async (id?: string) => {
    try {
      const data = await api.captcha(id)
      setCaptchaId(data.captcha_id)
      setCaptchaImage(data.image)
      setCredentials((c) => ({ ...c, captcha: '' }))
    } catch (e) {
      setError(e instanceof Error ? e.message : '验证码加载失败')
    }
  }, [])

  useEffect(() => {
    if (!token) refreshCaptcha()
  }, [token, refreshCaptcha])

  useEffect(() => {
    if (!token) return
    api.me(token)
      .then((p) => {
        const cleaned: StudentProfile = { ...p, major: cleanName(p.major), name: cleanName(p.name) }
        setProfile(cleaned)
        if (cleaned.major && !cleaned.major.startsWith('未识别')) setCurrentMajor(cleaned.major)
        // Auto-match grade from the school card; fall back to the student ID.
        const sidGrade = Number(String(p.student_id || '').match(/20\d{2}/)?.[0] || 0)
        const matchedGrade = cleaned.grade || sidGrade
        if (matchedGrade) setGrade(matchedGrade)
        if (p.gpa) setGpa(p.gpa)
      })
      .catch(() => {
        api.clearToken()
        setToken('')
        setNotice('登录已过期，请重新登录')
      })
    api.programOptions(token).then(setOptions).catch(() => undefined)
    api.programColleges(token)
      .then((data) => setCollegesData(data.colleges))
      .catch(() => undefined)
    api.rules().then(setRules).catch(() => undefined)
    api.transferStats().then((data) => {
      setStats(data)
      setGpaTargets(Object.keys(data.summary))
    }).catch(() => undefined)
  }, [token])

  // Cascade: selecting a college loads its real list of majors on demand.
  useEffect(() => {
    if (!token || !targetCollege || collegeMajorsMap[targetCollege]) return
    let cancelled = false
    api.programMajors(token, targetCollege, grade)
      .then((data) => {
        if (cancelled) return
        setCollegeMajorsMap((prev) => ({ ...prev, [targetCollege]: data.majors }))
        setMajorColleges((prev) => {
          const next = { ...prev }
          data.majors.forEach((m) => { next[m] = targetCollege })
          return next
        })
      })
      .catch(() => undefined)
    return () => { cancelled = true }
  }, [token, targetCollege, grade, collegeMajorsMap])

  useEffect(() => {
    api.demoPrograms().then(setPrograms).catch(() => undefined)
    api.rules().then(setRules).catch(() => undefined)
    api.transferStats().then((data) => {
      setStats(data)
      setGpaTargets(Object.keys(data.summary))
    }).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (token || !demoMajors.includes(currentMajor)) return
    try {
      const saved = JSON.parse(localStorage.getItem(PROFILE_KEY) || '{}') as { major?: string; grade?: number; gpa?: number }
      const nextMajor = demoMajors.includes(saved.major || '') ? saved.major! : demoMajors[0]
      if (nextMajor) setCurrentMajor(nextMajor)
      if (saved.grade) setGrade(saved.grade)
      if (saved.gpa) setGpa(saved.gpa)
    } catch { if (demoMajors[0]) setCurrentMajor(demoMajors[0]) }
  }, [token, demoMajors, currentMajor])

  useEffect(() => {
    if (!token) localStorage.setItem(PROFILE_KEY, JSON.stringify({ major: currentMajor, grade, gpa }))
  }, [token, currentMajor, grade, gpa])

  const buildProfile = useCallback(async (): Promise<StudentProfile> => {
    if (token && profile) {
      // Real transcript; keep only courses passed up to the chosen semester.
      return {
        ...profile,
        grade,
        completed: profile.completed.filter((c) => c.passed !== false && (c.semester ?? 8) <= progressSemester),
      }
    }
    const program = await api.demoProgram(currentMajor, grade)
    return {
      student_id: '本地档案',
      name: '我',
      major: currentMajor,
      grade,
      college: program.college,
      gpa,
      completed: program.courses
        .filter((c) => c.category !== '选修' && (c.semester ?? 8) <= progressSemester)
        .map((c) => ({ ...c, score: '80', passed: true })),
    }
  }, [token, profile, currentMajor, grade, gpa, progressSemester])

  const runCompare = useCallback(async () => {
    if (!currentMajor || !targetMajors.length) return
    setLoading(true)
    setError('')
    try {
      const activeProfile = await buildProfile()
      const response = await api.compare({
        profile: activeProfile,
        current_major: currentMajor,
        target_majors: targetMajors,
        grade,
        source: token ? 'live' : 'demo',
        token: token || undefined,
        major_colleges: majorColleges,
        rules,
      })
      setResult(response)
      if (response.fetch_errors?.length) {
        setError('部分培养方案抓取失败：' + response.fetch_errors.join('；'))
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '对比失败')
    } finally {
      setLoading(false)
    }
  }, [buildProfile, currentMajor, targetMajors, grade, token, rules, majorColleges])

  useEffect(() => {
    if (majors.length && currentMajor && targetMajors.length) void runCompare()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, currentMajor, grade, gpa, progressSemester, targetMajors.join(','), majors.length])

  useEffect(() => {
    if (!gpa || !gpaTargets.length) return
    let cancelled = false
    api.gpaEstimate(gpa, gpaTargets)
      .then((data) => { if (!cancelled) setGpaResults(data.items) })
      .catch(() => undefined)
    return () => { cancelled = true }
  }, [gpa, gpaTargets.join(',')])

  const handleLogin = async (event: FormEvent) => {
    event.preventDefault()
    setLoading(true)
    setError('')
    try {
      const response = await api.login(captchaId, credentials.username, credentials.password, credentials.captcha)
      if (!response.ok) {
        setError(response.message)
        if (response.captcha_id) await refreshCaptcha(response.captcha_id)
        return
      }
      api.storeToken(response.token!)
      setToken(response.token!)
      const cleaned: StudentProfile = response.profile
        ? { ...response.profile, major: cleanName(response.profile.major), name: cleanName(response.profile.name) }
        : (null as unknown as StudentProfile)
      setProfile(cleaned)
      setNotice('')
      if (response.profile?.major && !cleaned.major.startsWith('未识别')) setCurrentMajor(cleaned.major)
      const sidGrade = Number(String(response.profile?.student_id || '').match(/20\d{2}/)?.[0] || 0)
      const matchedGrade = cleaned.grade || sidGrade
      if (matchedGrade) setGrade(matchedGrade)
      if (response.profile?.gpa) setGpa(response.profile.gpa)
    } catch (e) {
      setError(e instanceof Error ? e.message : '登录失败')
      await refreshCaptcha()
    } finally {
      setLoading(false)
    }
  }

  const logout = () => {
    api.clearToken()
    setToken('')
    setProfile(null)
    setOptions({})
    setResult(null)
    setCurrentMajor('')
    setTargetMajors([])
    refreshCaptcha()
  }

  const toggleTarget = (major: string) => {
    setTargetMajors((prev) => prev.includes(major) ? prev.filter((m) => m !== major) : [...prev, major])
  }
  const selectAllCollege = () => setTargetMajors((prev) => Array.from(new Set([
    ...prev, ...collegeMajors.filter((m) => m !== currentMajor),
  ])))
  const clearCollege = () => setTargetMajors((prev) => prev.filter((m) => !collegeMajors.includes(m)))

  // ---------- Login screen ----------
  if (!token) {
    return (
      <div className="app-shell">
        <header className="header">
          <div className="header-inner">
            <div>
              <h1>广财转专业助手</h1>
              <p>登录融合门户 · 自动匹配专业 · 培养方案差异对比 · 补修学分核算</p>
            </div>
          </div>
        </header>
        <main className="login-page">
          <div className="login-layout">
            <form className="card login-card" onSubmit={handleLogin}>
              <h2>使用融合门户账号登录</h2>
              <p className="muted">登录后自动读取你的专业、年级与成绩单，并从教务系统拉取全部专业的培养方案。账号密码只在本地发起一次登录请求，本站不保存。</p>
              <label>学号 / 账号</label>
              <input value={credentials.username} onChange={(e) => setCredentials({ ...credentials, username: e.target.value })} autoComplete="username" required />
              <label>教务系统密码</label>
              <input type="password" value={credentials.password} onChange={(e) => setCredentials({ ...credentials, password: e.target.value })} autoComplete="current-password" required />
              <label>验证码（点击图片刷新）</label>
              <div className="captcha-row">
                <input value={credentials.captcha} onChange={(e) => setCredentials({ ...credentials, captcha: e.target.value })} maxLength={6} required />
                {captchaImage
                  ? <button type="button" className="captcha-image" onClick={() => refreshCaptcha()} title="点击刷新验证码"><img src={captchaImage} alt="验证码" /></button>
                  : <span className="muted">加载中…</span>}
              </div>
              {error && <div className="alert alert-error">{error}</div>}
              <button className="primary wide" disabled={loading}>{loading ? '登录中…' : '登录并同步我的专业'}</button>
            </form>
            <section className="card guide login-guide">
              <h2>登录后你可以做什么</h2>
              <ol className="guide-steps">
                <li>自动识别<strong>你的专业和年级</strong>，无需手动挑选。</li>
                <li>从教务系统读取<strong>全部专业</strong>的培养方案，先选学院再选专业。</li>
                <li>用你的<strong>真实成绩单</strong>对比：必修课重合、需补修课程、学分缺口与课程替代。</li>
                <li>按 2024 级公示名单查看绩点位次参考（仅历史参考，非录取概率）。</li>
              </ol>
              <p className="muted guide-note">验证码由你本人查看输入，本站不识别、不绕过。请遵守学校信息系统使用规定。</p>
            </section>
          </div>
        </main>
      </div>
    )
  }

  // ---------- Main dashboard ----------
  return (
    <div className="app-shell">
      <header className="header">
        <div className="header-inner">
          <div>
            <h1>广财转专业助手</h1>
            <p>已登录教务系统 · 自动匹配专业 · 培养方案差异对比 · 真实成绩单核算</p>
          </div>
          <div className="header-actions">
            <span className="user-chip">{profile?.name || '同学'} · {profile?.major || currentMajor}</span>
            <button className="ghost small" onClick={logout}>退出登录</button>
          </div>
        </div>
      </header>
      <main className="container">
        {notice && <div className="alert alert-info" onClick={() => setNotice('')}>{notice}</div>}
        {error && <div className="alert alert-error" onClick={() => setError('')}>{error}</div>}

        <section className="card controls">
          <div className="control-row">
            <div>
              <label>入学年级</label>
              <select value={grade} onChange={(e) => {
                const nextGrade = Number(e.target.value)
                setGrade(nextGrade)
                setTargetCollege('')
                setCollegeMajorsMap({})
              }}>
                {grades.map((g) => <option key={g} value={g}>{g} 级</option>)}
              </select>
            </div>
            <div>
              <label>我的专业（已自动匹配）</label>
              <select value={currentMajor} onChange={(e) => setCurrentMajor(e.target.value)}>
                {!majors.includes(currentMajor) && <option value={currentMajor}>{currentMajor || '加载中…'}</option>}
                {collegeGroups.length
                  ? collegeGroups.map(([college, groupMajors]) => (
                    <optgroup key={college} label={college}>
                      {groupMajors.filter((m) => majors.includes(m)).map((m) => <option key={m} value={m}>{m}</option>)}
                    </optgroup>
                  ))
                  : majors.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
            <div>
              <label>我的累积绩点</label>
              <input type="number" step="0.0001" min="0" max="5" value={gpa || ''} placeholder="例如 3.8" onChange={(e) => setGpa(Number(e.target.value))} />
            </div>
            <div>
              <label>已读到第几学期</label>
              <select value={progressSemester} onChange={(e) => setProgressSemester(Number(e.target.value))}>
                {Array.from({ length: 8 }, (_, i) => i + 1).map((s) => <option key={s} value={s}>第 {s} 学期末</option>)}
              </select>
            </div>
            <div className="grow target-picker">
              <label>对比目标：先选学院，再选专业（可多选）</label>
              <select value={targetCollege} onChange={(e) => setTargetCollege(e.target.value)}>
                <option value="">全部学院</option>
                {colleges.map((college) => <option key={college.value} value={college.value}>{college.label}</option>)}
              </select>
              <div className="chips">
                {collegeMajors.filter((m) => m !== currentMajor).map((m) => (
                  <button key={m} className={`chip ${targetMajors.includes(m) ? 'chip-active' : ''}`} onClick={() => toggleTarget(m)}>{m}</button>
                ))}
              </div>
              <div className="chip-actions">
                <button className="link" onClick={selectAllCollege}>全选当前学院</button>
                <button className="link" onClick={clearCollege}>清空当前学院</button>
                <span className="muted">共 {majors.length} 个专业 · 已选 {targetMajors.length} 个</span>
              </div>
            </div>
            <div className="action-column">
              <button className="primary" onClick={runCompare} disabled={loading || !targetMajors.length}>
                {loading ? '计算中…' : '开始对比'}
              </button>
            </div>
          </div>
        </section>

        <section className="stat-grid">
          <Stat label="当前专业" value={currentMajor} hint={profile?.name || '已自动匹配'} />
          <Stat label="已修学分" value={primary?.earned_credits ?? 0} hint="真实成绩单（按学期过滤）" />
          <Stat label="重合必修课" value={primary?.overlap_count ?? 0} tone="good" hint="两个专业都要求" />
          <Stat label="需补修" value={`${primary?.missing_count ?? 0} 门`} tone="warn" hint={`${primary?.missing_credits ?? 0} 学分`} />
          <Stat label="总学分缺口" value={primary?.credit_gap ?? 0} tone="warn" hint="目标专业总学分口径" />
          <Stat label="最省补修" value={best?.major || '—'} tone="good" hint={best ? `补 ${best.missing_count} 门` : ''} />
        </section>

        <section className="card">
          <div className="tabs">
            {([
              ['overview', '差异总览'],
              ['missing', '补修清单'],
              ['substitution', '课程替代'],
              ['ranking', '专业推荐排序'],
              ['gpa', '绩点成功率参考'],
              ['source', '数据来源'],
            ] as [Tab, string][]).map(([key, label]) => (
              <button key={key} className={tab === key ? 'tab-active' : ''} onClick={() => setTab(key)}>{label}</button>
            ))}
          </div>

          <div className="tab-content">
            {tab === 'overview' && (
              <div className="overview-grid">
                <div>
                  <h3>必修课重合（{primary?.overlap_count ?? 0}）</h3>
                  <p className="muted">这些课程两个专业都要求，通常不需要重修。</p>
                  <CourseTable courses={primary?.overlap_courses || []} empty="暂无重合数据" />
                </div>
                <div>
                  <h3>需要补修（{primary?.missing_count ?? 0} 门 / {primary?.missing_credits ?? 0} 学分）</h3>
                  <p className="muted">目标专业要求、而你尚未修读或未被认定通过的课程。</p>
                  <CourseTable courses={primary?.missing_courses || []} empty="没有需要补修的课程 🎉" />
                </div>
              </div>
            )}
            {tab === 'missing' && (
              <>
                <h3>{primary?.major || '目标专业'} 补修清单</h3>
                <CourseTable courses={primary?.missing_courses || []} empty="没有需要补修的课程" />
                <p className="muted">
                  补修学分合计：<strong>{primary?.missing_credits ?? 0}</strong>；
                  转专业后总学分缺口：<strong>{primary?.credit_gap ?? 0}</strong>
                  （保守口径：仅计入匹配目标要求的课程和已修通识选修课，其余由学院认定）。
                </p>
              </>
            )}
            {tab === 'substitution' && (
              <>
                <h3>可做课程替代 / 已被认定的学分</h3>
                <SubstitutionTable items={primary?.substitutions || []} />
                <p className="muted">当前规则库共 {rules.length} 条。规则仅提供线索，最终以目标学院教务认定为准。欢迎在 GitHub 提交经过核实的新规则。</p>
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>原课程</th><th>替代目标</th><th>说明</th></tr></thead>
                    <tbody>
                      {rules.map((rule) => (
                        <tr key={rule.id}>
                          <td>{rule.from_name || rule.from_code}</td>
                          <td>{rule.to_name || rule.to_code}</td>
                          <td className="muted">{rule.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
            {tab === 'ranking' && (
              <>
                <h3>哪个专业补的课程最少？</h3>
                <p className="muted">按“需补修门数 → 补修学分 → 总学分缺口”排序，点击专业可设为对比目标。</p>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr><th>排名</th><th>目标专业</th><th>补修门数</th><th>补修学分</th><th>学分缺口</th><th>重合必修</th><th>可转移学分</th><th></th></tr>
                    </thead>
                    <tbody>
                      {(result?.ranking || []).map((row, i) => (
                        <tr key={row.major} className={row.major === primary?.major ? 'row-selected' : ''}>
                          <td>{i + 1}</td>
                          <td className="strong">{row.major}</td>
                          <td>{row.missing_count}</td>
                          <td>{row.missing_credits}</td>
                          <td>{row.credit_gap}</td>
                          <td>{row.overlap_count}</td>
                          <td>{row.transferable_credits}</td>
                          <td><button className="link" onClick={() => { setTargetMajors([row.major]); setTab('overview') }}>查看</button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
            {tab === 'gpa' && (
              <>
                <div className="gpa-header">
                  <div>
                    <h3>2024 级转专业绩点参考</h3>
                    <p className="muted">
                      基于《2024级普教本科生专业二次选择拟转专业学生名单》（匿名化，{stats ? Object.keys(stats.summary).length : 0} 个目标专业）。
                      输入你的累积绩点，查看你在历史名单中的位次。
                      目前仅公布 2024 级名单，其他年级（含 2026 级）暂无对应数据，请仅作参考。
                    </p>
                  </div>
                  <div className="gpa-input-box">
                    <label>我的绩点</label>
                    <input type="number" step="0.0001" min="0" max="5" value={gpa || ''} placeholder="例如 3.8" onChange={(e) => setGpa(Number(e.target.value))} />
                  </div>
                </div>
                <div className="alert alert-warn-note">
                  <strong>重要说明：</strong>原名单是“拟转专业公示名单”，不是最终录取名单，也不代表各专业招生计划。
                  下方“位次”仅表示你的绩点在历史名单中的相对位置，<strong>不是录取概率</strong>；能否转成功还取决于名额、类别、面试/考核与当年政策。
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr><th>目标专业</th><th>名单人数</th><th>最低绩点</th><th>中位绩点</th><th>最高绩点</th><th>我的位次</th><th>低于我的比例</th><th>参考判断</th></tr>
                    </thead>
                    <tbody>
                      {gpaResults.map((item) => (
                        <tr key={item.major}>
                          <td className="strong">{item.major}</td>
                          <td>{item.count}</td><td>{item.min}</td><td>{item.median}</td><td>{item.max}</td>
                          <td>第 {item.rank} / {item.count}</td>
                          <td><div className="percent-cell"><span>{item.percentile}%</span><div className="percent-bar"><div style={{ width: `${item.percentile}%` }} /></div></div></td>
                          <td><span className={`badge ${item.percentile >= 75 ? 'badge-good' : item.percentile >= 40 ? 'badge-warn' : 'badge-low'}`}>{item.level}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="muted">数据已匿名化（不含姓名与完整学号）。原始 PDF 由项目维护者提供，名单统计口径与学校公示文件一致。</p>
              </>
            )}
            {tab === 'source' && (
              <div>
                <h3>如何贡献真实数据</h3>
                <p className="muted">本项目开源，欢迎在 GitHub 提交经过核实的培养方案 JSON 或课程替代规则，并注明年级、学院与来源链接。具体格式见项目 README。</p>
              </div>
            )}
          </div>
        </section>

        <footer className="footer">数据仅供择校参考，最终修读与认定以广东财经大学教务处及各学院规定为准。</footer>
      </main>
    </div>
  )
}
