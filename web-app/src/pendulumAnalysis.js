const DEFAULT_PIVOT_X = 230
const DEFAULT_PIVOT_Y = 120

function solveLinearSystem(matrix, vector) {
  const n = vector.length
  const aug = matrix.map((row, idx) => [...row, vector[idx]])

  for (let i = 0; i < n; i++) {
    let pivot = i
    for (let r = i + 1; r < n; r++) {
      if (Math.abs(aug[r][i]) > Math.abs(aug[pivot][i])) pivot = r
    }

    if (Math.abs(aug[pivot][i]) < 1e-12) {
      return null
    }

    if (pivot !== i) {
      const tmp = aug[i]
      aug[i] = aug[pivot]
      aug[pivot] = tmp
    }

    const pivotVal = aug[i][i]
    for (let c = i; c <= n; c++) {
      aug[i][c] /= pivotVal
    }

    for (let r = 0; r < n; r++) {
      if (r === i) continue
      const factor = aug[r][i]
      for (let c = i; c <= n; c++) {
        aug[r][c] -= factor * aug[i][c]
      }
    }
  }

  return aug.map((row) => row[n])
}

function savgolFilter(values, windowLength, polyorder) {
  const n = values.length
  const half = Math.floor(windowLength / 2)
  const out = new Array(n)
  const features = polyorder + 1

  for (let i = 0; i < n; i++) {
    const start = Math.max(0, i - half)
    const end = Math.min(n - 1, i + half)

    const gram = Array.from({ length: features }, () => Array(features).fill(0))
    const b = Array(features).fill(0)

    for (let j = start; j <= end; j++) {
      const x = j - i
      const powers = [1]
      for (let p = 1; p < features; p++) {
        powers[p] = powers[p - 1] * x
      }

      const y = values[j]
      for (let r = 0; r < features; r++) {
        b[r] += powers[r] * y
        for (let c = 0; c < features; c++) {
          gram[r][c] += powers[r] * powers[c]
        }
      }
    }

    const coeffs = solveLinearSystem(gram, b)
    out[i] = coeffs ? coeffs[0] : values[i]
  }

  return out
}

export function savgolOrOriginal(values, polyorder = 3) {
  const count = values.length
  if (count < polyorder + 2) return [...values]

  let window = count > 50 ? 41 : 9
  if (window >= count) window = count % 2 === 1 ? count : count - 1
  if (window < polyorder + 2) return [...values]

  return savgolFilter(values, window, polyorder)
}

export function zeroCrossings(times, signal) {
  const result = []
  for (let i = 0; i < signal.length - 1; i++) {
    const y1 = signal[i]
    const y2 = signal[i + 1]
    if (y1 === 0 && y2 === 0) continue
    if (y1 === 0) {
      result.push(times[i])
      continue
    }
    if (y2 === 0) {
      result.push(times[i + 1])
      continue
    }
    if (y1 * y2 < 0) {
      const frac = -y1 / (y2 - y1)
      if (frac >= 0 && frac <= 1) {
        const t = times[i] + frac * (times[i + 1] - times[i])
        result.push(t)
      }
    }
  }
  return result
}

function gradient(values, times) {
  const n = values.length
  if (n === 0) return []
  const out = new Array(n).fill(0)

  for (let i = 0; i < n; i++) {
    const tPrev = i > 0 ? times[i - 1] : times[i]
    const tNext = i < n - 1 ? times[i + 1] : times[i]
    const dtPrev = times[i] - tPrev || 1
    const dtNext = tNext - times[i] || 1

    if (i === 0) {
      out[i] = (values[i + 1] - values[i]) / dtNext
    } else if (i === n - 1) {
      out[i] = (values[i] - values[i - 1]) / dtPrev
    } else {
      out[i] = (values[i + 1] - values[i - 1]) / (dtPrev + dtNext)
    }
  }

  return out
}

export function computePhysicalStats(times, xs, ys, pivotX, pivotY) {
  if (times.length < 3) return null

  const px = pivotX ?? DEFAULT_PIVOT_X
  const py = pivotY ?? DEFAULT_PIVOT_Y

  const arrX = savgolOrOriginal(xs)
  const arrY = savgolOrOriginal(ys)

  const dx = arrX.map((v) => v - px)
  const dy = arrY.map((v) => v - py)

  const theta = dx.map((v, idx) => Math.atan2(v, dy[idx]))
  const thetaMean = theta.reduce((acc, val) => acc + val, 0) / theta.length
  const thetaCentered = theta.map((v) => v - thetaMean)
  const thetaDeg = theta.map((v) => (v * 180) / Math.PI)

  const crossings = zeroCrossings(times, thetaCentered)
  const oscillations = crossings.length ? crossings.length / 2 : 0
  const halfPeriods = []
  for (let i = 0; i < crossings.length - 1; i++) {
    halfPeriods.push(crossings[i + 1] - crossings[i])
  }

  const period = halfPeriods.length ? median(halfPeriods) * 2 : null
  const frequency = period && period > 0 ? 1 / period : null
  const angularFrequency = period && period > 0 ? (2 * Math.PI) / period : null

  const totalTime = times.length > 1 ? times[times.length - 1] - times[0] : 0
  const lengthPx = average(dx.map((v, idx) => Math.hypot(v, dy[idx])))

  const thetaDot = gradient(theta, times)
  const thetaDDot = gradient(thetaDot, times)

  const absMax = (arr) => arr.reduce((m, v) => Math.max(m, Math.abs(v)), 0)

  return {
    total_time: totalTime,
    samples: times.length,
    oscillations,
    period: period ?? null,
    frequency: frequency ?? null,
    angular_frequency: angularFrequency ?? null,
    max_angle_deg: absMax(thetaDeg),
    length_px: lengthPx,
    max_ang_velocity: absMax(thetaDot),
    max_ang_acceleration: absMax(thetaDDot),
    pivot_x: px,
    pivot_y: py,
  }
}

export function computeAngles(times, xs, ys, pivotX, pivotY) {
  const px = pivotX ?? DEFAULT_PIVOT_X
  const py = pivotY ?? DEFAULT_PIVOT_Y
  const xSmooth = savgolOrOriginal(xs)
  const ySmooth = savgolOrOriginal(ys)

  const theta = xSmooth.map((v, idx) => {
    const dy = ySmooth[idx] - py
    return (Math.atan2(v - px, dy) * 180) / Math.PI
  })
  const thetaSmooth = savgolOrOriginal(theta)

  const stats = computePhysicalStats(times, xSmooth, ySmooth, px, py)

  return { thetaRaw: theta, thetaSmooth, stats }
}

function average(arr) {
  if (!arr.length) return 0
  return arr.reduce((acc, v) => acc + v, 0) / arr.length
}

function median(arr) {
  if (!arr.length) return 0
  const sorted = [...arr].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid]
}

export const PIVOT_DEFAULTS = {
  x: DEFAULT_PIVOT_X,
  y: DEFAULT_PIVOT_Y,
}
