# Multi-stage build: compile with Maven, run on a slim JRE.
# Built with context = repo root (see docker-compose.yml) so this can COPY
# db/ (the Flyway migrations) without reaching outside the build context.
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /build
COPY services/decision-api/pom.xml .
RUN mvn -B dependency:go-offline
COPY services/decision-api/src ./src
RUN mvn -B -o package -DskipTests

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
RUN addgroup -S vigil && adduser -S vigil -G vigil
COPY --from=build /build/target/decision-api.jar app.jar
COPY db /app/db
USER vigil
EXPOSE 8081
ENV VIGIL_FLYWAY_LOCATION=/app/db
ENTRYPOINT ["java", "-Xmx512m", "-jar", "app.jar"]
