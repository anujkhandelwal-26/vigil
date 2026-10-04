package com.vigil.web;

import org.junit.jupiter.api.Test;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.web.server.ResponseStatusException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;

/** Pure unit test: each exception class maps to its own status, never the 500 catch-all. */
class ProblemDetailHandlerTest {

    private final ProblemDetailHandler handler = new ProblemDetailHandler();

    @Test
    void accessDeniedIs403() {
        assertEquals(403, handler.handleAccessDenied(new AccessDeniedException("nope")).getStatus());
    }

    @Test
    void dataIntegrityViolationIs409AndDoesNotLeakSql() {
        ProblemDetail pd = handler.handleDataIntegrity(new DataIntegrityViolationException(
                "could not execute statement; constraint [application_external_ref_key]"));
        assertEquals(409, pd.getStatus());
        assertFalse(String.valueOf(pd.getDetail()).contains("application_external_ref_key"));
    }

    @Test
    void errorResponseExceptionsKeepTheirOwnStatus() {
        ResponseEntity<ProblemDetail> resp =
                handler.handleGeneric(new ResponseStatusException(HttpStatus.NOT_FOUND, "missing"));
        assertEquals(404, resp.getStatusCode().value());
    }

    @Test
    void unknownExceptionIs500WithGenericMessage() {
        ResponseEntity<ProblemDetail> resp = handler.handleGeneric(new RuntimeException("select * from secret"));
        assertEquals(500, resp.getStatusCode().value());
        assertEquals("An unexpected error occurred", resp.getBody().getDetail());
    }
}
