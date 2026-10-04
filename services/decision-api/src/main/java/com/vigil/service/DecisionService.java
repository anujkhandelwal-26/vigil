package com.vigil.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.vigil.api.dto.*;
import com.vigil.domain.Application;
import com.vigil.domain.Decision;
import com.vigil.repo.ApplicationRepository;
import com.vigil.repo.DecisionRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * Orchestrates the real-time scoring path (see docs/architecture.md for
 * the latency budget): assemble server-side velocity features -> run the
 * deterministic RuleEngine -> call ml-service (timeout-bounded, degrades
 * gracefully) -> combine rule + model actions by severity -> persist.
 * The LLM is never on this path.
 */
@Service
public class DecisionService {

    private static final List<String> ACTION_ORDER = List.of("APPROVE", "STEP_UP", "REVIEW", "DECLINE");

    // With the model down, the rules alone can't see synthetic-identity or
    // novel patterns, so nothing is auto-approved: every degraded decision
    // goes to a human at minimum.
    static final String DEGRADED_FLOOR = "REVIEW";

    private final ApplicationRepository applicationRepository;
    private final DecisionRepository decisionRepository;
    private final FeatureAssembler featureAssembler;
    private final RuleEngine ruleEngine;
    private final MlClient mlClient;
    private final AuditService auditService;
    private final ObjectMapper objectMapper;

    public DecisionService(ApplicationRepository applicationRepository, DecisionRepository decisionRepository,
                            FeatureAssembler featureAssembler, RuleEngine ruleEngine, MlClient mlClient,
                            AuditService auditService, ObjectMapper objectMapper) {
        this.applicationRepository = applicationRepository;
        this.decisionRepository = decisionRepository;
        this.featureAssembler = featureAssembler;
        this.ruleEngine = ruleEngine;
        this.mlClient = mlClient;
        this.auditService = auditService;
        this.objectMapper = objectMapper;
    }

    @Transactional
    public DecisionResponse submitAndScore(ApplicationSubmitRequest req, String actorUsername) {
        long t0 = System.currentTimeMillis();

        // Velocity is counted before the insert, so this application isn't
        // counted against itself.
        FeatureAssembler.Velocity velocity = featureAssembler.assemble(req);

        Application app = mapToEntity(req);
        // Persist what the rules and model actually saw, not the client's claim.
        app.setDeviceReuseCount30d(velocity.deviceReuseCount30d());
        app.setIpDistinctApps24h(velocity.ipDistinctApps24h());
        app.setAccountSharedWithNApplicants(velocity.accountSharedWithNApplicants());
        app = applicationRepository.save(app);

        RuleEngine.RuleResult ruleResult = ruleEngine.evaluate(req, velocity.deviceReuseCount30d(), velocity.ipDistinctApps24h(), velocity.accountSharedWithNApplicants());

        MlScoreRequest mlReq = MlScoreRequest.from(app.getId().toString(), req,
                velocity.deviceReuseCount30d(), velocity.ipDistinctApps24h(), velocity.accountSharedWithNApplicants());
        MlClient.ScoreOutcome outcome = mlClient.score(mlReq);

        String finalAction;
        BigDecimal riskScore;
        BigDecimal anomalyScore = null;
        String modelVersion;
        List<String> reasonCodes = new ArrayList<>();
        String shapTopJson = null;

        Set<String> combinedReasons = new LinkedHashSet<>(ruleResult.reasonCodes());

        // A 2xx is not trusted blindly: a response with no usable action or score
        // is treated exactly like an outage, so it can never auto-approve.
        MlScoreResponse mlResp = outcome.response();
        boolean degraded = outcome.degraded() || mlResp == null || mlResp.riskScore() == null
                || mlResp.action() == null || !ACTION_ORDER.contains(mlResp.action());

        if (degraded) {
            finalAction = maxSeverity(ruleResult.action(), DEGRADED_FLOOR);
            riskScore = null; // no model score exists; never show a fabricated 0
            modelVersion = "rules-only";
            combinedReasons.add("ML_UNAVAILABLE_RULES_ONLY");
        } else {
            MlScoreResponse ml = mlResp;
            finalAction = maxSeverity(ruleResult.action(), ml.action());
            riskScore = ml.riskScore();
            anomalyScore = ml.anomalyScore();
            modelVersion = ml.modelVersion();
            if (ml.reasonCodes() != null) combinedReasons.addAll(ml.reasonCodes());
            try {
                shapTopJson = objectMapper.writeValueAsString(ml.shapTop());
            } catch (Exception ignored) {
                shapTopJson = "[]";
            }
        }
        reasonCodes.addAll(combinedReasons);

        int latencyMs = (int) (System.currentTimeMillis() - t0);

        Decision decision = new Decision();
        decision.setApplicationId(app.getId());
        decision.setModelVersion(modelVersion);
        decision.setRiskScore(riskScore);
        decision.setAnomalyScore(anomalyScore);
        decision.setAction(finalAction);
        decision.setReasonCodes(reasonCodes.toArray(new String[0]));
        decision.setShapTop(shapTopJson);
        decision.setLatencyMs(latencyMs);
        decision.setDegraded(degraded);
        decisionRepository.save(decision);

        auditService.log(actorUsername, "SUBMIT_AND_SCORE", "application", app.getId().toString(),
                "action=" + finalAction + " risk_score=" + (riskScore == null ? "n/a" : riskScore) + " latency_ms=" + latencyMs);

        List<String> verificationSteps = finalAction.equals("STEP_UP")
                ? List.of("Mobile OTP verification", "Aadhaar OTP e-KYC (offline XML)", "DigiLocker PAN fetch", "Penny-drop bank verification")
                : List.of();

        String kfs = finalAction.equals("APPROVE")
                ? buildKeyFactStatement(req)
                : null;

        return new DecisionResponse(app.getId(), app.getExternalRef(), finalAction, riskScore, anomalyScore,
                reasonCodes, shapTopJson, modelVersion, latencyMs, degraded, verificationSteps, kfs);
    }

    private String buildKeyFactStatement(ApplicationSubmitRequest req) {
        // RBI Digital Lending Directions, 2025: a Key Fact Statement is shown
        // before loan execution, with all-in cost disclosed and a cooling-off
        // period stated. This is a simplified, illustrative KFS for the demo.
        BigDecimal apr = BigDecimal.valueOf(16.5);
        return String.format(
                "Key Fact Statement: Loan amount INR %s, tenure %d months, indicative APR %s%%. " +
                "You may exit this loan within a 1-day cooling-off period by repaying the principal " +
                "and proportionate interest, with no penalty, per RBI Digital Lending Directions, 2025.",
                req.amountInr().toPlainString(), req.tenureMonths(), apr.toPlainString());
    }

    private String maxSeverity(String a, String b) {
        int ia = ACTION_ORDER.indexOf(a);
        int ib = ACTION_ORDER.indexOf(b);
        return ia >= ib ? a : b;
    }

    private Application mapToEntity(ApplicationSubmitRequest r) {
        Application a = new Application();
        a.setExternalRef(r.externalRef());
        a.setAge(r.age());
        a.setGender(r.gender());
        a.setEmploymentType(r.employmentType());
        a.setMonthlyIncomeInr(r.monthlyIncomeInr());
        a.setCityTier(r.cityTier());
        a.setPincodePrefix(r.pincodePrefix());
        a.setResidenceType(r.residenceType());
        a.setProduct(r.product());
        a.setAmountInr(r.amountInr());
        a.setTenureMonths(r.tenureMonths());
        a.setChannel(r.channel());
        a.setCibilScore(r.cibilScore());
        a.setIsNewToCredit(r.isNewToCredit());
        a.setActiveLoans(r.activeLoans());
        a.setEnquiries30d(r.enquiries30d());
        a.setMaxDpd12m(r.maxDpd12m());
        a.setCreditUtilisationPct(r.creditUtilisationPct());
        a.setOldestAccountMonths(r.oldestAccountMonths());
        a.setPanFormatValid(r.panFormatValid());
        a.setPanNameMatchScore(r.panNameMatchScore());
        a.setAadhaarPanLinked(r.aadhaarPanLinked());
        a.setNameDobMismatch(r.nameDobMismatch());
        a.setDigilockerDocsFetched(r.digilockerDocsFetched());
        a.setAadhaarLast4(r.aadhaarLast4());
        a.setDeviceHash(r.deviceHash());
        a.setDeviceReuseCount30d(r.deviceReuseCount30d());
        a.setIsEmulator(r.isEmulator());
        a.setIsRooted(r.isRooted());
        a.setAppInstallAgeDays(r.appInstallAgeDays());
        a.setIpPrefix(r.ipPrefix());
        a.setIpDistinctApps24h(r.ipDistinctApps24h());
        a.setIpPincodeDistanceKm(r.ipPincodeDistanceKm());
        a.setVpnOrProxy(r.vpnOrProxy());
        a.setFormFillSeconds(r.formFillSeconds());
        a.setTypingSpeedCpm(r.typingSpeedCpm());
        a.setPasteEvents(r.pasteEvents());
        a.setFieldCorrections(r.fieldCorrections());
        a.setSessionScreens(r.sessionScreens());
        a.setNightApplication(r.nightApplication());
        a.setTimeSincePrevAppHours(r.timeSincePrevAppHours());
        a.setBankAccountHash(r.bankAccountHash());
        a.setPennyDropNameMatch(r.pennyDropNameMatch());
        a.setAccountAgeMonths(r.accountAgeMonths());
        a.setAvgMonthlyCreditInr(r.avgMonthlyCreditInr());
        a.setSalaryCreditRegularity(r.salaryCreditRegularity());
        a.setBounceCount6m(r.bounceCount6m());
        a.setAccountSharedWithNApplicants(r.accountSharedWithNApplicants());
        a.setMobileHash(r.mobileHash());
        a.setMobileAgeOnNetworkDays(r.mobileAgeOnNetworkDays());
        a.setRecentSimSwap30d(r.recentSimSwap30d());
        a.setMobileNameMatch(r.mobileNameMatch());
        return a;
    }
}
