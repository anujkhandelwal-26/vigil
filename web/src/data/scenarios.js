// Application payloads for the Apply dashboard's scenario dropdown. Every
// field is editable in the form after a scenario is picked -- this is what
// makes the demo interactive rather than a canned replay.
//
// The base record for each scenario is pulled at random from real synthetic
// applications (see src/demo-fixtures — explicitly labelled as demo-only
// logic) rather than a single hardcoded template, so picking the same
// scenario twice, or reloading the page, gives a fresh, varied record
// instead of the exact same fields every time.
import { randomSample } from '../demo-fixtures/index.js'

function freshRef() {
  // Must match the backend's ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ and stay unique
  // (the column is UNIQUE): timestamp + random suffix. crypto.randomUUID only
  // exists in secure contexts, so plain-http LAN access falls back to Math.random.
  const rand = globalThis.crypto?.randomUUID?.().slice(0, 8)
    ?? Math.random().toString(36).slice(2, 10)
  return `APP-DEMO-${Date.now().toString(36)}-${rand}`
}

export const SCENARIOS = {
  CLEAN: {
    label: 'Clean salaried applicant',
    build: () => ({ externalRef: freshRef(), ...randomSample('CLEAN') }),
  },
  DEVICE_FARM: {
    label: 'Device farm (bot ring)',
    build: () => ({ externalRef: freshRef(), ...randomSample('DEVICE_FARM') }),
  },
  SYNTHETIC_IDENTITY: {
    label: 'Synthetic identity',
    build: () => ({ externalRef: freshRef(), ...randomSample('SYNTHETIC_IDENTITY') }),
  },
  MULE_ACCOUNT_RING: {
    label: 'Mule account ring',
    build: () => ({ externalRef: freshRef(), ...randomSample('MULE_ACCOUNT_RING') }),
  },
  SIM_SWAP: {
    label: 'SIM-swap takeover',
    build: () => ({ externalRef: freshRef(), ...randomSample('SIM_SWAP_TAKEOVER') }),
  },
  INCOME_INFLATION: {
    label: 'Income inflation',
    build: () => ({ externalRef: freshRef(), ...randomSample('INCOME_INFLATION') }),
  },
  BOT_RING_NEW_VECTOR: {
    // Deliberately NOT randomized from data/generated/new_vector_injection.csv:
    // every row in that file scores risk_score=1.000 (correctly declined) --
    // it's more extreme than this scenario needs. This exact, hand-tuned
    // combination is a genuinely different, moderate one that does NOT reuse
    // the DEVICE_FARM training signature (extreme device_reuse, is_emulator,
    // sub-10s fill), and was measured directly against ml-service
    // /internal/score before wiring into the UI: risk_score=0.000 (the
    // calibrated model fully misses it), anomaly_score=0.949 (the
    // IsolationForest novelty channel screams). That gap IS the demo: a
    // supervised model trained only on known typologies would let this
    // through; the parallel unsupervised channel is what catches it.
    label: '⚠ New bot ring (unseen by training)',
    build: () => ({
      externalRef: freshRef(),
      age: 29, gender: 'F', employmentType: 'SALARIED', monthlyIncomeInr: 62000,
      cityTier: 2, pincodePrefix: '560', residenceType: 'RENTED',
      product: 'CONSUMER_DURABLE', amountInr: 85000, tenureMonths: 12, channel: 'ANDROID_APP',
      cibilScore: 730, isNewToCredit: false, activeLoans: 2, enquiries30d: 1,
      maxDpd12m: 0, creditUtilisationPct: 20, oldestAccountMonths: 60,
      panFormatValid: true, panNameMatchScore: 0.9, aadhaarPanLinked: true,
      nameDobMismatch: false, digilockerDocsFetched: 2, aadhaarLast4: '4821',
      deviceHash: 'sha256:bot-ring-new-vector-demo', deviceReuseCount30d: 2,
      isEmulator: false, isRooted: true, appInstallAgeDays: 20,
      ipPrefix: '103.21', ipDistinctApps24h: 4, vpnOrProxy: true,
      formFillSeconds: 25, typingSpeedCpm: 380, pasteEvents: 3,
      fieldCorrections: 0, sessionScreens: 3, nightApplication: true,
      timeSincePrevAppHours: 1200,
      bankAccountHash: 'sha256:bank-newvector', pennyDropNameMatch: 0.97,
      accountAgeMonths: 42, avgMonthlyCreditInr: 60000, salaryCreditRegularity: 0.92,
      bounceCount6m: 0, accountSharedWithNApplicants: 1,
      mobileHash: 'sha256:mob-newvector', mobileAgeOnNetworkDays: 820,
      recentSimSwap30d: false, mobileNameMatch: 0.96,
    }),
  },
  VELOCITY_BURST: {
    label: 'Velocity burst (rapid re-apply)',
    // No dedicated generator typology for this one -- it's a real clean
    // record with the re-application-velocity fields overridden on top.
    build: () => ({
      externalRef: freshRef(),
      ...randomSample('CLEAN'),
      enquiries30d: 8,
      timeSincePrevAppHours: 0.2,
      ipDistinctApps24h: 3,
    }),
  },
}
