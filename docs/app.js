/* All content comes from the checked-in benchmark; no external chart services. */
let benchmark;
const $ = id => document.getElementById(id);
const colors = {Backtracking: '#2673a5', 'A*': '#087e81', 'Genetic Algorithm': '#8855ad'};
const number = (value, digits = 2) => value == null ? '—' : Number(value).toFixed(digits);
const escapeHTML = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
const clock = minutes => `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;

function renderSchedule() {
  const caseInfo = benchmark.cases.find(c => c.id === $('scenario').value);
  const run = benchmark.runs.find(r => r.case === caseInfo.id && r.method === $('schedule-method').value && r.seed === Number($('schedule-seed').value));
  if (!run || !run.valid) {
    $('schedule-summary').textContent = run ? `${run.method} · Seed ${run.seed} · ${run.message || 'No valid schedule returned.'}` : 'No measured run available.';
    $('schedule-grid').innerHTML = '';
    $('schedule-body').innerHTML = '<tr><td colspan="4">No valid schedule available for this run.</td></tr>';
    return;
  }
  const nodesText = run.nodes != null ? ` · ${Number(run.nodes).toLocaleString()} nodes` : '';
  $('schedule-summary').textContent = `${run.method} · Seed ${run.seed} · ${number(run.runtime_sec, 3)} s${nodesText} · ${number(run.academic_units, 0)} academic units · Fitness ${number(run.fitness)} · Total gaps ${run.gap_minutes} min · Average gap ${number(run.average_gap, 1)} min${caseInfo.gap_minutes ? ` · Target ${caseInfo.gap_minutes} min · Target error ${number(run.gap_target_error, 1)} min` : ''}`;
  const days = ['M','T','W','Th','F','S'];
  const labels = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
  const palette = ['#cfe8ff','#ffd9b3','#d9f2d0','#f9d1e6','#e6dcff','#fff3b0','#c8f1ee','#ffd0d0','#e3e3e3','#d5e8c8'];
  const left = 110, width = 150, header = 38, start = 420, finish = 1140;
  const y = minute => header + minute - start;
  let drawing = `<rect width="1010" height="38" fill="#20313b"/><text x="55" y="25" text-anchor="middle" fill="white" font-size="15">Time</text>`;
  labels.forEach((day, index) => { drawing += `<text x="${left + index * width + width / 2}" y="25" text-anchor="middle" fill="white" font-size="15">${day}</text>`; });
  for (let minute = start; minute < finish; minute += 30) {
    drawing += `<rect x="0" y="${y(minute)}" width="${left}" height="30" fill="#edf2f6"/><text x="55" y="${y(minute) + 20}" text-anchor="middle" font-size="13" fill="#20313b">${clock(minute)}–${clock(minute + 30)}</text><line x1="0" x2="1010" y1="${y(minute)}" y2="${y(minute)}" stroke="#dbe2e8"/>`;
  }
  for (let day = 0; day <= 6; day++) drawing += `<line x1="${left + day * width}" x2="${left + day * width}" y1="0" y2="758" stroke="#dbe2e8"/>`;
  caseInfo.blocked.forEach(([day, slot]) => { drawing += `<rect x="${left + day * width + 1}" y="${header + slot * 30 + 1}" width="148" height="28" fill="#dcdcdc"><title>Unavailable: ${labels[day]} ${clock(start + slot * 30)}–${clock(start + (slot + 1) * 30)}</title></rect>`; });
  run.schedule.forEach((section, index) => {
    const clash = section.meetings.some(([day, begin, end]) => caseInfo.blocked.some(([d, slot]) => days[d] === day && begin < start + (slot + 1) * 30 && end > start + slot * 30));
    section.meetings.forEach(([day, begin, end]) => {
      if (!days.includes(day)) return;
      const top = Math.max(start, begin), bottom = Math.min(finish, end);
      if (bottom <= top) return;
      const x = left + days.indexOf(day) * width + 2, mid = x + 73, height = bottom - top - 2;
      const description = `${section.course_code} · ${section.section} · ${day} ${clock(begin)}–${clock(end)}${clash ? ' · overlaps unavailable hours' : ''}`;
      drawing += `<g><title>${escapeHTML(description)}</title><rect x="${x}" y="${y(top) + 1}" width="146" height="${height}" rx="3" fill="${palette[index % palette.length]}" stroke="${clash ? '#b00020' : '#777'}" stroke-width="${clash ? 2 : 1}"/><text x="${mid}" y="${y(top) + height / 2 - (height >= 55 ? 12 : height >= 40 ? 6 : 0)}" text-anchor="middle" fill="#20313b" font-size="14" font-weight="600">${escapeHTML(section.course_code)}</text>`;
      if (height >= 40) drawing += `<text x="${mid}" y="${y(top) + height / 2 + (height >= 55 ? 6 : 12)}" text-anchor="middle" fill="#20313b" font-size="13">${escapeHTML(section.section)}</text>`;
      if (height >= 55) drawing += `<text x="${mid}" y="${y(top) + height / 2 + 23}" text-anchor="middle" fill="#20313b" font-size="12">${clock(begin)}–${clock(end)}</text>`;
      drawing += '</g>';
    });
  });
  $('schedule-grid').innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1010 758" role="img" aria-labelledby="timetable-title timetable-description" style="font-family:Segoe UI,Arial,sans-serif"><title id="timetable-title">${escapeHTML(run.method)} weekly timetable, seed ${run.seed}</title><desc id="timetable-description">Monday to Saturday, 07:00 to 19:00, in 30-minute slots. Classes are colored; unavailable hours are gray. Full meeting details appear in the course list below.</desc>${drawing}</svg>`;
  $('schedule-body').innerHTML = run.schedule.map(section => {
    const unitLabel = section.units != null ? `${section.units}${section.hk ? ' (HK)' : ''}` : '—';
    return `<tr><th scope="row">${escapeHTML(section.course_code)}</th><td>${escapeHTML(section.section)}</td><td>${escapeHTML(unitLabel)}</td><td>${section.meetings.map(([day,begin,end]) => `${day} ${clock(begin)}–${clock(end)}`).join('; ') || 'No fixed time'}</td></tr>`;
  }).join('');
}

function drawChart(id, rows, metric, title, suffix, digits) {
  const values = rows.map(row => row[metric]).filter(value => value != null);
  const minimum = Math.min(0, ...values);
  const maximum = Math.max(1, ...values);
  const x = value => (value - minimum) / (maximum - minimum) * 480;
  const baseline = x(0);
  const bars = rows.map((row, index) => {
    const y = 24 + index * 72;
    const value = row[metric];
    const end = value == null ? baseline : x(value);
    return `<text x="0" y="${y}" fill="#102a34" font-size="22">${escapeHTML(row.method)}</text>
      <text x="480" y="${y}" text-anchor="end" fill="#102a34" font-size="22">${number(value, digits)}${value == null ? '' : suffix}</text>
      <rect x="0" y="${y + 13}" width="480" height="19" rx="3" fill="#edf2f4"/>
      <rect x="${Math.min(baseline, end)}" y="${y + 13}" width="${Math.abs(end - baseline)}" height="19" rx="3" fill="${colors[row.method]}"/>`;
  }).join('');
  $(id).innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 490 245" role="img" aria-labelledby="${id}-title ${id}-desc" style="font-family:Segoe UI,Arial,sans-serif;background:white"><title id="${id}-title">${escapeHTML(title)}</title><desc id="${id}-desc">${escapeHTML(rows.map(r => `${r.method}: ${number(r[metric], digits)}${r[metric] == null ? '' : suffix}`).join('; '))}. Values are also in the comparison table.</desc>${bars}<text x="0" y="235" font-size="18" fill="#526874">${number(minimum, digits)}</text><text x="480" y="235" text-anchor="end" font-size="18" fill="#526874">${number(maximum, digits)}${suffix}</text></svg>`;
}

function renderScenario() {
  const caseInfo = benchmark.cases.find(c => c.id === $('scenario').value);
  const rows = benchmark.summary.filter(row => row.case === caseInfo.id);
  $('case-note').textContent = `${caseInfo.program} (${caseInfo.specialization}) · ${caseInfo.year} · ${caseInfo.semester} · ${caseInfo.blocked.length ? 'M/W/F 08:00–10:00 unavailable' : 'No unavailable hours'} · ${caseInfo.gap_minutes ? `Target gap: ${caseInfo.gap_minutes} min (Backtracking & A*)` : 'No target gap (minimize idle time)'}`;
  $('summary-caption').textContent = caseInfo.label + ' — medians across repeated runs';
  $('summary-body').innerHTML = rows.map(row => `<tr><th scope="row">${escapeHTML(row.method)}</th><td>${row.valid_runs} / ${row.runs}</td><td>${number(row.median_runtime, 4)}</td><td>${number(row.fitness)}</td><td>${number(row.academic_units, 0)}</td><td>${row.nodes != null ? Number(row.nodes).toLocaleString() : '—'}</td><td>${number(row.gap_minutes, 0)}</td><td>${number(row.average_gap, 1)}</td><td>${number(row.gap_target_error, 1)}</td><td>${number(row.blocked_count, 0)}</td><td>${row.timeouts}</td></tr>`).join('');
  drawChart('runtime-chart', rows, 'median_runtime', `Runtime: ${caseInfo.label}`, ' s', 4);
  drawChart('fitness-chart', rows, 'fitness', `Fitness: ${caseInfo.label}`, '', 2);
  drawChart('gap-chart', rows, 'gap_minutes', `Idle time: ${caseInfo.label}`, ' min', 0);
  drawChart('valid-chart', rows, 'success_pct', `Valid schedules: ${caseInfo.label}`, '%', 0);
  $('gap-error-card').hidden = !caseInfo.gap_minutes;
  if (caseInfo.gap_minutes) drawChart('gap-error-chart', rows, 'gap_target_error', `Target gap error: ${caseInfo.label}`, ' min', 1);
  const valid = rows.filter(row => row.valid_runs);
  if (valid.length) {
    const best = Math.max(...valid.map(row => row.fitness));
    const leaders = valid.filter(row => row.fitness === best).map(row => row.method).join(' and ');
    $('finding-text').textContent = `${leaders} achieved the highest median fitness (${number(best)}). ${rows.reduce((sum,row) => sum + row.valid_runs, 0)} of ${rows.reduce((sum,row) => sum + row.runs, 0)} runs produced valid schedules in this scenario.`;
  } else $('finding-text').textContent = 'No method returned a valid schedule in this scenario within the configured limits.';
  renderSchedule();
}

async function init() {
  try {
    const response = await fetch('data/results.json');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    benchmark = await response.json();
    const config = benchmark.config;
    $('bt-budget').textContent = `${config.node_limit.toLocaleString()} nodes max`;
    $('astar-budget').textContent = `${config.node_limit.toLocaleString()} nodes max`;
    $('ga-budget').textContent = `${config.generations.toLocaleString()} generations · ${config.population} individuals · ${(config.mutation_rate * 100).toFixed(0)}% mutation rate`;
    $('scenario').innerHTML = benchmark.cases.map(c => `<option value="${escapeHTML(c.id)}">${escapeHTML(c.label)}</option>`).join('');
    $('study-note').textContent = `${benchmark.runs.length} total runs · ${config.repeats} seeds per method per scenario · ${config.timeout_sec}-second wall-clock cap per run.`;
    $('scenario').addEventListener('change', renderScenario);
    $('schedule-seed').innerHTML = Array.from({length:config.repeats}, (_, seed) => `<option value="${seed}">Seed ${seed}</option>`).join('');
    $('schedule-method').addEventListener('change', renderSchedule);
    $('schedule-seed').addEventListener('change', renderSchedule);
    renderScenario();
    $('results-content').hidden = false;
    $('load-status').hidden = true;
  } catch (error) {
    $('load-status').textContent = 'Results could not be loaded. Open this page through a local HTTP server (see README), or download the CSV directly. ' + error.message;
  }
}
init();
