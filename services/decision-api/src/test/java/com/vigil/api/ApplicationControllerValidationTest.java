package com.vigil.api;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.vigil.repo.AnalystFeedbackRepository;
import com.vigil.repo.AppUserRepository;
import com.vigil.repo.ApplicationRepository;
import com.vigil.repo.DecisionRepository;
import com.vigil.service.AuditService;
import com.vigil.service.DecisionService;
import com.vigil.service.MlClient;
import com.vigil.config.JwtService;
import com.vigil.service.QueryService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.HashMap;
import java.util.Map;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * @WebMvcTest with security filters disabled -- this test's job is Bean
 * Validation coverage only (input validation), not authentication (401
 * behaviour is exercised live: see README "Verification" for the curl
 * check that a missing Authorization header returns 401).
 *
 * All controller dependencies are mocked so this never touches a
 * database or ml-service -- fast, isolated, no Testcontainers needed.
 */
@WebMvcTest(controllers = ApplicationController.class)
@AutoConfigureMockMvc(addFilters = false)
class ApplicationControllerValidationTest {

    @Autowired
    private MockMvc mockMvc;

    private final ObjectMapper objectMapper = new ObjectMapper();

    @MockitoBean private DecisionService decisionService;
    @MockitoBean private QueryService queryService;
    @MockitoBean private ApplicationRepository applicationRepository;
    @MockitoBean private DecisionRepository decisionRepository;
    @MockitoBean private AnalystFeedbackRepository feedbackRepository;
    @MockitoBean private MlClient mlClient;
    @MockitoBean private AuditService auditService;
    @MockitoBean private AppUserRepository appUserRepository;
    @MockitoBean private JwtService jwtService;

    private Map<String, Object> validPayload() {
        Map<String, Object> m = new HashMap<>();
        m.put("externalRef", "APP-TEST-1");
        m.put("age", 30);
        m.put("gender", "F");
        m.put("employmentType", "SALARIED");
        m.put("monthlyIncomeInr", 50000);
        m.put("cityTier", 2);
        m.put("pincodePrefix", "560");
        m.put("residenceType", "RENTED");
        m.put("product", "CONSUMER_DURABLE");
        m.put("amountInr", 50000);
        m.put("tenureMonths", 12);
        m.put("channel", "ANDROID_APP");
        m.put("cibilScore", 720);
        m.put("isNewToCredit", false);
        m.put("activeLoans", 1);
        m.put("enquiries30d", 1);
        m.put("maxDpd12m", 0);
        m.put("creditUtilisationPct", 30);
        m.put("oldestAccountMonths", 40);
        m.put("panFormatValid", true);
        m.put("panNameMatchScore", 0.95);
        m.put("aadhaarPanLinked", true);
        m.put("nameDobMismatch", false);
        m.put("digilockerDocsFetched", 2);
        m.put("aadhaarLast4", "1234");
        m.put("deviceHash", "dev-hash");
        m.put("deviceReuseCount30d", 0);
        m.put("isEmulator", false);
        m.put("isRooted", false);
        m.put("appInstallAgeDays", 100);
        m.put("ipPrefix", "1.2");
        m.put("ipDistinctApps24h", 1);
        m.put("ipPincodeDistanceKm", 5);
        m.put("vpnOrProxy", false);
        m.put("formFillSeconds", 150);
        m.put("typingSpeedCpm", 180);
        m.put("pasteEvents", 0);
        m.put("fieldCorrections", 2);
        m.put("sessionScreens", 6);
        m.put("nightApplication", false);
        m.put("timeSincePrevAppHours", 500);
        m.put("bankAccountHash", "bank-hash");
        m.put("pennyDropNameMatch", 0.95);
        m.put("accountAgeMonths", 30);
        m.put("avgMonthlyCreditInr", 48000);
        m.put("salaryCreditRegularity", 0.9);
        m.put("bounceCount6m", 0);
        m.put("accountSharedWithNApplicants", 1);
        m.put("mobileHash", "mobile-hash");
        m.put("mobileAgeOnNetworkDays", 500);
        m.put("recentSimSwap30d", false);
        m.put("mobileNameMatch", 0.95);
        return m;
    }

    @Test
    void rejectsNegativeLoanAmountWith400() throws Exception {
        Map<String, Object> payload = validPayload();
        payload.put("amountInr", -5000);

        mockMvc.perform(post("/api/v1/applications")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(payload)))
                .andExpect(status().isBadRequest());
    }

    @Test
    void rejectsMissingRequiredFieldWith400() throws Exception {
        Map<String, Object> payload = validPayload();
        payload.remove("deviceHash");

        mockMvc.perform(post("/api/v1/applications")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(payload)))
                .andExpect(status().isBadRequest());
    }

    @Test
    void rejectsExternalRefOutsideAllowedPatternWith400() throws Exception {
        for (String bad : new String[] {"has space", "-leading", "a".repeat(65), "x'; DROP"}) {
            Map<String, Object> payload = validPayload();
            payload.put("externalRef", bad);
            mockMvc.perform(post("/api/v1/applications")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content(objectMapper.writeValueAsString(payload)))
                    .andExpect(status().isBadRequest());
        }
    }

    @Test
    void rejectsNumericOverflowingTheColumnWith400() throws Exception {
        Map<String, Object> payload = validPayload();
        payload.put("creditUtilisationPct", 1000); // NUMERIC(5,2) holds at most 999.99

        mockMvc.perform(post("/api/v1/applications")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(payload)))
                .andExpect(status().isBadRequest());
    }

    @Test
    void rejectsMalformedJsonWith400() throws Exception {
        mockMvc.perform(post("/api/v1/applications")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{not json"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void rejectsOutOfRangeLimitWith400() throws Exception {
        for (String limit : new String[] {"-1", "0", "501", "abc"}) {
            mockMvc.perform(get("/api/v1/applications").param("limit", limit))
                    .andExpect(status().isBadRequest());
        }
    }

    @Test
    void rejectsMalformedIdPathVariableWith400() throws Exception {
        mockMvc.perform(get("/api/v1/applications/not-a-uuid")).andExpect(status().isBadRequest());
    }

    @Test
    void rejectsMalformedPincodePrefixWith400() throws Exception {
        Map<String, Object> payload = validPayload();
        payload.put("pincodePrefix", "not-a-pincode");

        mockMvc.perform(post("/api/v1/applications")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(payload)))
                .andExpect(status().isBadRequest());
    }

}
