package com.vigil.domain;

import tools.jackson.databind.json.JsonMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * GET /api/v1/applications/{id} serialises the Application entity. The
 * generator's ground-truth labels and the protected / PII fields must never
 * reach an API client.
 */
class ApplicationSerializationTest {

    @Test
    void groundTruthLabelsAndProtectedFieldsAreNeverSerialised() throws Exception {
        Application a = new Application();
        a.setExternalRef("APP-1");
        a.setLabelFraud(true);
        a.setLabelTypology("MULE_ACCOUNT_RING");
        a.setGender("F");
        a.setAadhaarLast4("1234");

        String json = JsonMapper.builder().build().writeValueAsString(a);

        assertTrue(json.contains("APP-1"));
        assertFalse(json.contains("labelFraud"));
        assertFalse(json.contains("MULE_ACCOUNT_RING"));
        assertFalse(json.contains("gender"));
        assertFalse(json.contains("1234"));
    }
}
