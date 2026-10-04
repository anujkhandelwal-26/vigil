package com.vigil.config;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.web.client.RestClient;

/**
 * Two RestClients to ml-service, both using a snake_case-configured
 * ObjectMapper (MlScoreRequest/Response are camelCase Java records,
 * matching ml-service's pydantic snake_case schema automatically -- no
 * manual field mapping).
 *
 *  - mlScoreRestClient: SHORT timeout (vigil.ml-service.timeout-ms,
 *    default 150ms). This is the hot path -- if ml-service doesn't answer
 *    in time, MlClient falls back to a rules-only degraded decision.
 *  - mlLlmRestClient: LONG timeout (30s). Narrative/copilot calls go
 *    through Ollama and legitimately take up to a few seconds; these are
 *    never on the scoring hot path.
 */
@Configuration
public class MlRestClientConfig {

    @Bean
    public ObjectMapper objectMapper() {
        return new ObjectMapper();
    }

    private RestClient build(VigilProperties props, int connectTimeoutMs, int readTimeoutMs) {
        ObjectMapper snakeCaseMapper = new ObjectMapper()
                .setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
                // A new ml-service response field must not silently degrade every score.
                .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);
        MappingJackson2HttpMessageConverter converter = new MappingJackson2HttpMessageConverter(snakeCaseMapper);

        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(connectTimeoutMs);
        factory.setReadTimeout(readTimeoutMs);

        return RestClient.builder()
                .baseUrl(props.mlService().url())
                .requestFactory(factory)
                .messageConverters(converters -> {
                    converters.clear();
                    converters.add(converter);
                })
                .build();
    }

    @Bean
    public RestClient mlScoreRestClient(VigilProperties props) {
        int timeoutMs = props.mlService().timeoutMs() > 0 ? props.mlService().timeoutMs() : 150;
        return build(props, timeoutMs, timeoutMs);
    }

    @Bean
    public RestClient mlLlmRestClient(VigilProperties props) {
        return build(props, 5000, 30000);
    }
}
