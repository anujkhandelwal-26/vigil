package com.vigil.domain;

import com.fasterxml.jackson.annotation.JsonIgnore;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * A submitted loan application. Six data blocks (applicant, loan, bureau,
 * kyc, device, behaviour, banking, mobile) -- see README.md "Training
 * record" for the field dictionary. Protected attributes (age, gender) are
 * stored here but the feature-building layer in ml-service never reads
 * them as model inputs -- they exist for the post-hoc fairness audit only.
 *
 * Every column name is explicit (not left to Hibernate's implicit naming
 * strategy) -- several field names here contain digit/acronym boundaries
 * (e.g. accountSharedWithNApplicants, ipDistinctApps24h) that the default
 * CamelCase-to-underscore converter does not split the way db/V1__schema.sql
 * does, so relying on it silently produces the wrong column name.
 */
@Entity
@Table(name = "application")
@Getter
@Setter
@NoArgsConstructor
public class Application {

    @Id
    @GeneratedValue
    @Column(name = "id")
    private UUID id;

    @Column(name = "external_ref", nullable = false, unique = true)
    private String externalRef;

    @Column(name = "submitted_at", nullable = false)
    private OffsetDateTime submittedAt = OffsetDateTime.now();

    @Column(name = "age", nullable = false) private Integer age;
    @JsonIgnore @Column(name = "gender", nullable = false) private String gender;
    @Column(name = "employment_type", nullable = false) private String employmentType;
    @Column(name = "monthly_income_inr", nullable = false) private BigDecimal monthlyIncomeInr;
    @Column(name = "city_tier", nullable = false) private Integer cityTier;
    @Column(name = "pincode_prefix", nullable = false) private String pincodePrefix;
    @Column(name = "residence_type", nullable = false) private String residenceType;

    @Column(name = "product", nullable = false) private String product;
    @Column(name = "amount_inr", nullable = false) private BigDecimal amountInr;
    @Column(name = "tenure_months", nullable = false) private Integer tenureMonths;
    @Column(name = "channel", nullable = false) private String channel;

    @Column(name = "cibil_score") private Integer cibilScore;
    @Column(name = "is_new_to_credit", nullable = false) private Boolean isNewToCredit;
    @Column(name = "active_loans", nullable = false) private Integer activeLoans;
    @Column(name = "enquiries_30d", nullable = false) private Integer enquiries30d;
    @Column(name = "max_dpd_12m", nullable = false) private Integer maxDpd12m;
    @Column(name = "credit_utilisation_pct") private BigDecimal creditUtilisationPct;
    @Column(name = "oldest_account_months") private Integer oldestAccountMonths;

    @Column(name = "pan_format_valid", nullable = false) private Boolean panFormatValid;
    @Column(name = "pan_name_match_score", nullable = false) private BigDecimal panNameMatchScore;
    @Column(name = "aadhaar_pan_linked", nullable = false) private Boolean aadhaarPanLinked;
    @Column(name = "name_dob_mismatch", nullable = false) private Boolean nameDobMismatch;
    @Column(name = "digilocker_docs_fetched", nullable = false) private Integer digilockerDocsFetched;
    @JsonIgnore @Column(name = "aadhaar_last4") private String aadhaarLast4;

    @Column(name = "device_hash", nullable = false) private String deviceHash;
    @Column(name = "device_reuse_count_30d", nullable = false) private Integer deviceReuseCount30d;
    @Column(name = "is_emulator", nullable = false) private Boolean isEmulator;
    @Column(name = "is_rooted", nullable = false) private Boolean isRooted;
    @Column(name = "app_install_age_days", nullable = false) private Integer appInstallAgeDays;
    @Column(name = "ip_prefix", nullable = false) private String ipPrefix;
    @Column(name = "ip_distinct_apps_24h", nullable = false) private Integer ipDistinctApps24h;
    @Column(name = "ip_pincode_distance_km") private BigDecimal ipPincodeDistanceKm;
    @Column(name = "vpn_or_proxy", nullable = false) private Boolean vpnOrProxy;

    @Column(name = "form_fill_seconds", nullable = false) private BigDecimal formFillSeconds;
    @Column(name = "typing_speed_cpm") private BigDecimal typingSpeedCpm;
    @Column(name = "paste_events", nullable = false) private Integer pasteEvents;
    @Column(name = "field_corrections", nullable = false) private Integer fieldCorrections;
    @Column(name = "session_screens", nullable = false) private Integer sessionScreens;
    @Column(name = "night_application", nullable = false) private Boolean nightApplication;
    @Column(name = "time_since_prev_app_hours") private BigDecimal timeSincePrevAppHours;

    @Column(name = "bank_account_hash", nullable = false) private String bankAccountHash;
    @Column(name = "penny_drop_name_match") private BigDecimal pennyDropNameMatch;
    @Column(name = "account_age_months") private Integer accountAgeMonths;
    @Column(name = "avg_monthly_credit_inr") private BigDecimal avgMonthlyCreditInr;
    @Column(name = "salary_credit_regularity") private BigDecimal salaryCreditRegularity;
    @Column(name = "bounce_count_6m", nullable = false) private Integer bounceCount6m;
    @Column(name = "account_shared_with_n_applicants", nullable = false) private Integer accountSharedWithNApplicants;

    @Column(name = "mobile_hash", nullable = false) private String mobileHash;
    @Column(name = "mobile_age_on_network_days") private Integer mobileAgeOnNetworkDays;
    @Column(name = "recent_sim_swap_30d", nullable = false) private Boolean recentSimSwap30d;
    @Column(name = "mobile_name_match") private BigDecimal mobileNameMatch;

    // Never serialised to API clients: the labels are the generator's answer
    // key, and gender / Aadhaar digits are fairness-audit and PII fields the
    // analyst UI doesn't need.
    @JsonIgnore @Column(name = "label_fraud") private Boolean labelFraud;
    @JsonIgnore @Column(name = "label_typology") private String labelTypology;

    @Column(name = "created_at", nullable = false)
    private OffsetDateTime createdAt = OffsetDateTime.now();
}
