package com.htc.bff;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest(classes = BffApplication.class)
@AutoConfigureMockMvc
class ChatControllerTest {
  @Autowired
  private MockMvc mockMvc;

  @Test
  void chatReturnsMockSuccessResponse() throws Exception {
    mockMvc.perform(post("/api/v1/chat")
        .contentType(MediaType.APPLICATION_JSON)
        .content("""
            {
              "query": "项目 Q1 阶段需要完成哪些功能？",
              "session_id": "local-session-001",
              "stream": false
            }
            """))
        .andExpect(status().isOk())
        .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
        .andExpect(jsonPath("$.trace_id").isNotEmpty())
        .andExpect(jsonPath("$.status").value("success"))
        .andExpect(jsonPath("$.answer").isNotEmpty())
        .andExpect(jsonPath("$.citations").isArray())
        .andExpect(jsonPath("$.citations[0].title").value("HTC Q1 MVP Requirement"));
  }

  @Test
  void chatRejectsBlankQuery() throws Exception {
    mockMvc.perform(post("/api/v1/chat")
        .contentType(MediaType.APPLICATION_JSON)
        .content("""
            {
              "query": "   ",
              "session_id": "local-session-001",
              "stream": false
            }
            """))
        .andExpect(status().isBadRequest());
  }
}
