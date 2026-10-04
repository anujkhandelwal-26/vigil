package com.vigil.domain;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.UUID;

@Entity
@Table(name = "analyst_feedback")
@Getter
@Setter
@NoArgsConstructor
public class AnalystFeedback {

    @Id
    @GeneratedValue
    @Column(name = "id")
    private UUID id;

    @Column(name = "application_id", nullable = false)
    private UUID applicationId;

    @Column(name = "analyst_id")
    private UUID analystId;

    @Column(name = "verdict", nullable = false)
    private String verdict; // FRAUD | LEGIT

    @Column(name = "original_action", nullable = false)
    private String originalAction;

    @Column(name = "original_score")
    private BigDecimal originalScore;

    @Column(name = "was_false_positive", nullable = false)
    private Boolean wasFalsePositive;

    @Column(name = "note")
    private String note;

    @Column(name = "created_at", nullable = false)
    private OffsetDateTime createdAt = OffsetDateTime.now();
}
