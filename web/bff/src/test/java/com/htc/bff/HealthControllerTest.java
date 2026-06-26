package com.htc.bff;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.options;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest(classes = HealthControllerTest.TestApplication.class)
@AutoConfigureMockMvc
class HealthControllerTest {
  @Autowired
  private MockMvc mockMvc;

  @Autowired
  private Environment environment;

  @Test
  void healthEndpointReturnsOkJson() throws Exception {
    mockMvc.perform(get("/api/v1/health"))
        .andExpect(status().isOk())
        .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
        .andExpect(jsonPath("$.status").value("ok"));
  }

  @Test
  void corsAllowsLocalhostViteOrigin() throws Exception {
    mockMvc.perform(options("/api/v1/health")
        .header(HttpHeaders.ORIGIN, "http://localhost:5173")
        .header(HttpHeaders.ACCESS_CONTROL_REQUEST_METHOD, "GET"))
        .andExpect(status().isOk())
        .andExpect(header().string(HttpHeaders.ACCESS_CONTROL_ALLOW_ORIGIN, "http://localhost:5173"));
  }

  @Test
  void corsAllowsLoopbackViteOrigin() throws Exception {
    mockMvc.perform(options("/api/v1/health")
        .header(HttpHeaders.ORIGIN, "http://127.0.0.1:5173")
        .header(HttpHeaders.ACCESS_CONTROL_REQUEST_METHOD, "GET"))
        .andExpect(status().isOk())
        .andExpect(header().string(HttpHeaders.ACCESS_CONTROL_ALLOW_ORIGIN, "http://127.0.0.1:5173"));
  }

  @Test
  void serverPortIs8080() {
    assertThat(environment.getProperty("server.port")).isEqualTo("8080");
  }

  @SpringBootApplication
  static class TestApplication {
  }
}
