package com.vigil.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.vigil.api.dto.ApplicationSubmitRequest;
import com.vigil.api.dto.DecisionResponse;
import com.vigil.api.dto.MlScoreResponse;
import com.vigil.domain.Application;
import com.vigil.domain.Decision;
import com.vigil.repo.ApplicationRepository;
import com.vigil.repo.DecisionRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;

import java.math.BigDecimal;
import java.util.List;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Pure unit tests with Mockito, no Spring context or database. Covers the
 * orchestration RuleEngineTest can't see: velocity counted before the
 * insert (so an application never counts against itself), and the
 * fail-safe degraded path when ml-service is down.
 */
class DecisionServiceTest {

    private ApplicationRepository applicationRepository;
    private DecisionRepository decisionRepository;
    private MlClient mlClient;
    private DecisionService service;

    @BeforeEach
    void setUp() {
        applicationRepository = mock(ApplicationRepository.class);
        mlClient = mock(MlClient.class);
        when(applicationRepository.save(any(Application.class))).thenAnswer(inv -> {
            Application a = inv.getArgument(0);
            a.setId(UUID.randomUUID());
            return a;
        });
        decisionRepository = mock(DecisionRepository.class);
        service = new DecisionService(applicationRepository, decisionRepository,
                new FeatureAssembler(applicationRepository), new RuleEngine(), mlClient,
                mock(AuditService.class), new ObjectMapper());
    }

    /** The clean request from RuleEngineTest, with client-supplied velocity at its floor. */
    private ApplicationSubmitRequest cleanRequest() {
        return new ApplicationSubmitRequest(
                "APP-TEST", 30, "F", "SALARIED", BigDecimal.valueOf(50000), 2, "560", "RENTED",
                "CONSUMER_DURABLE", BigDecimal.valueOf(50000), 12, "ANDROID_APP",
                720, false, 1, 1, 0, BigDecimal.valueOf(30), 40,
                true, BigDecimal.valueOf(0.95), true, false, 2, "1234",
                "dev-hash", 0, false, false, 100, "1.2", 1, BigDecimal.valueOf(5), false,
                BigDecimal.valueOf(150), BigDecimal.valueOf(180), 0, 2, 6, false, BigDecimal.valueOf(500),
                "bank-hash", BigDecimal.valueOf(0.95), 30, BigDecimal.valueOf(48000), BigDecimal.valueOf(0.9), 0, 1,
                "mobile-hash", 500, false, BigDecimal.valueOf(0.95)
        );
    }

    private void mlApproves() {
        when(mlClient.score(any())).thenReturn(new MlClient.ScoreOutcome(new MlScoreResponse(
                BigDecimal.valueOf(0.01), BigDecimal.valueOf(0.1), "APPROVE", List.of(), List.of(), "v1.0.0", 5), false));
    }

    @Test
    void velocityIsCountedBeforeTheApplicationIsSaved() {
        mlApproves();
        service.submitAndScore(cleanRequest(), "analyst");

        InOrder order = inOrder(applicationRepository);
        order.verify(applicationRepository).countByBankAccountHashSince(eq("bank-hash"), any());
        order.verify(applicationRepository).save(any(Application.class));
    }

    @Test
    void firstEverApplicationIsNotCountedAgainstItself() {
        // No prior rows: the repository counts are all 0.
        mlApproves();
        ArgumentCaptor<Application> saved = ArgumentCaptor.forClass(Application.class);
        DecisionResponse resp = service.submitAndScore(cleanRequest(), "analyst");

        verify(applicationRepository).save(saved.capture());
        assertEquals(0, saved.getValue().getDeviceReuseCount30d(), "no OTHER application on this device");
        assertEquals(1, saved.getValue().getIpDistinctApps24h(), "just this applicant on the IP");
        assertEquals(1, saved.getValue().getAccountSharedWithNApplicants(), "just this applicant on the account");
        assertEquals("APPROVE", resp.action());
    }

    @Test
    void bankAccountSharedWithThreePriorApplicantsCountsFourAndDeclines() {
        when(applicationRepository.countByBankAccountHashSince(anyString(), any())).thenReturn(3L);
        mlApproves();
        DecisionResponse resp = service.submitAndScore(cleanRequest(), "analyst");

        assertEquals("DECLINE", resp.action());
        assertTrue(resp.reasonCodes().contains("BANK_ACCOUNT_SHARED"));
    }

    @Test
    void bankAccountWithTwoPriorApplicantsDoesNotTripTheSharedAccountRule() {
        // Before the fix this counted 2 prior + self (flushed) + 1 = 4 -> DECLINE.
        when(applicationRepository.countByBankAccountHashSince(anyString(), any())).thenReturn(2L);
        mlApproves();
        DecisionResponse resp = service.submitAndScore(cleanRequest(), "analyst");

        assertEquals("APPROVE", resp.action());
    }

    @Test
    void mlOutageNeverAutoApproves() {
        when(mlClient.score(any())).thenReturn(new MlClient.ScoreOutcome(null, true));
        DecisionResponse resp = service.submitAndScore(cleanRequest(), "analyst");

        assertEquals(DecisionService.DEGRADED_FLOOR, resp.action());
        assertTrue(resp.degraded());
        assertTrue(resp.reasonCodes().contains("ML_UNAVAILABLE_RULES_ONLY"));
        assertNull(resp.keyFactStatement(), "no loan offer is made on a degraded decision");
    }

    @Test
    void mlResponseWithNullActionIsTreatedAsDegradedNeverApprove() {
        when(mlClient.score(any())).thenReturn(new MlClient.ScoreOutcome(new MlScoreResponse(
                BigDecimal.valueOf(0.01), BigDecimal.valueOf(0.1), null, List.of(), List.of(), "v1.0.0", 5), false));
        DecisionResponse resp = service.submitAndScore(cleanRequest(), "analyst");

        assertEquals(DecisionService.DEGRADED_FLOOR, resp.action());
        assertTrue(resp.degraded());
        assertTrue(resp.reasonCodes().contains("ML_UNAVAILABLE_RULES_ONLY"));
        assertNull(resp.riskScore());
    }

    @Test
    void mlResponseWithUnknownActionOrNullScoreIsDegraded() {
        when(mlClient.score(any())).thenReturn(new MlClient.ScoreOutcome(new MlScoreResponse(
                BigDecimal.valueOf(0.01), null, "WAVE_THROUGH", List.of(), List.of(), "v1.0.0", 5), false));
        assertTrue(service.submitAndScore(cleanRequest(), "analyst").degraded());

        when(mlClient.score(any())).thenReturn(new MlClient.ScoreOutcome(new MlScoreResponse(
                null, null, "APPROVE", List.of(), List.of(), "v1.0.0", 5), false));
        DecisionResponse resp = service.submitAndScore(cleanRequest(), "analyst");
        assertTrue(resp.degraded());
        assertEquals(DecisionService.DEGRADED_FLOOR, resp.action());
    }

    @Test
    void nullResponseWithoutDegradedFlagIsPersistedAsDegradedWithNullScore() {
        when(mlClient.score(any())).thenReturn(new MlClient.ScoreOutcome(null, false));
        DecisionResponse resp = service.submitAndScore(cleanRequest(), "analyst");

        assertTrue(resp.degraded());
        assertNull(resp.riskScore(), "rules-only decisions carry no model score");
        ArgumentCaptor<Decision> saved = ArgumentCaptor.forClass(Decision.class);
        verify(decisionRepository).save(saved.capture());
        assertTrue(saved.getValue().getDegraded());
        assertNull(saved.getValue().getRiskScore());
    }

    @Test
    void mlOutageStillHonoursAHarsherRuleAction() {
        when(applicationRepository.countByBankAccountHashSince(anyString(), any())).thenReturn(3L);
        when(mlClient.score(any())).thenReturn(new MlClient.ScoreOutcome(null, true));
        DecisionResponse resp = service.submitAndScore(cleanRequest(), "analyst");

        assertEquals("DECLINE", resp.action());
    }
}
