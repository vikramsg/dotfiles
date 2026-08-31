import Foundation
import Testing
@testable import MacflowCore

@Suite struct HTTPTests {
    @Test func testParserWaitsForCompleteBody() {
        let incomplete = Data("POST /v1/test HTTP/1.1\r\nContent-Length: 5\r\n\r\n123".utf8)
        #expect(HTTPParser.parse(incomplete) == nil)

        let complete = Data("POST /v1/test?a=b HTTP/1.1\r\nContent-Length: 5\r\n\r\n12345".utf8)
        let request = HTTPParser.parse(complete)
        #expect(request?.method == "POST")
        #expect(request?.path == "/v1/test")
        #expect(request?.queryItems == ["a": "b"])
        #expect(String(data: request?.body ?? Data(), encoding: .utf8) == "12345")
    }

    @Test func testParserSkipsEmptyQueryKeys() {
        let request = HTTPParser.parse(Data("GET /v1/windows?= HTTP/1.1\r\n\r\n".utf8))
        #expect(request?.queryItems == [:])
    }

    @Test func testURLBuilderHandlesIPv6Loopback() {
        #expect(
            HTTPURLBuilder.make(host: "::1", port: 17421, path: "/v1/health")?.absoluteString
                == "http://[::1]:17421/v1/health"
        )
        #expect(
            HTTPURLBuilder.make(host: "127.0.0.1", port: 17421, path: "/v1/health")?.absoluteString
                == "http://127.0.0.1:17421/v1/health"
        )
    }

    @Test func testParserRejectsUnsafeContentLengths() {
        for value in ["-1", String(Int.max), "1048577", "invalid"] {
            let data = Data("POST / HTTP/1.1\r\nContent-Length: \(value)\r\n\r\n".utf8)
            #expect(HTTPParser.rejectionReason(data) == "Invalid Content-Length")
            #expect(HTTPParser.parse(data) == nil)
        }

        let duplicate = Data(
            "POST / HTTP/1.1\r\nContent-Length: 0\r\nContent-Length: 1048577\r\n\r\n".utf8
        )
        #expect(HTTPParser.rejectionReason(duplicate) == "Invalid Content-Length")
        #expect(HTTPParser.parse(duplicate) == nil)
    }
}
