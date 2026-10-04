package com.vigil.domain;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.UUID;

@Entity
@Table(name = "decision")
@Getter
@Setter
@NoArgsConstructor
public class Decision {

    @Id
    @GeneratedValue
    @Column(name = "id")
    private UUID id;

    @Column(name = "application_id", nullable = false)
    private UUID applicationId;

    @Column(name = "model_version", nullable = false)
    private String modelVersion;

    // Null on rules-only (degraded) decisions: there is no model score to show.
    @Column(name = "risk_score")
    private BigDecimal riskScore;

    @Column(name = "anomaly_score")
    private BigDecimal anomalyScore;

    @Column(name = "rule_score")
    private BigDecimal ruleScore;

    @Column(name = "action", nullable = false)
    private String action;

    @JdbcTypeCode(SqlTypes.ARRAY)
    @Column(name = "reason_codes")
    private String[] reasonCodes;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "shap_top")
    private String shapTop;

    @Column(name = "latency_ms", nullable = false)
    private Integer latencyMs;

    @Column(name = "degraded", nullable = false)
    private Boolean degraded = false;

    @Column(name = "created_at", nullable = false)
    private OffsetDateTime createdAt = OffsetDateTime.now();
}
