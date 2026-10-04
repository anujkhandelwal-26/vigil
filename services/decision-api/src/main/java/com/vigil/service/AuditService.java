package com.vigil.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.Collections;

/**
 * Every decision, override and retrain is written here with actor and
 * timestamp -- the audit trail backing "secure API usage" / "responsible
 * data handling". Kept as a raw JdbcTemplate insert (not a JPA entity)
 * since audit_log.payload is a free-form JSONB blob, not a fixed shape.
 */
@Service
public class AuditService {

    private final JdbcTemplate jdbcTemplate;

    private final ObjectMapper objectMapper;

    public AuditService(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    public void log(String actor, String action, String entity, String entityId, String note) {
        String payload;
        try {
            payload = objectMapper.writeValueAsString(Collections.singletonMap("note", note));
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("cannot serialise audit payload", e);
        }
        jdbcTemplate.update(
                "INSERT INTO audit_log (actor, action, entity, entity_id, payload) VALUES (?, ?, ?, ?, ?::jsonb)",
                actor, action, entity, entityId, payload);
    }
}
