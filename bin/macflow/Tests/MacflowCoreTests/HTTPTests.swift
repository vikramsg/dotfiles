import Foundation
import XCTest
@testable import MacflowCore

final class HTTPTests: XCTestCase {
    func testParserWaitsForCompleteBody() {
        let incomplete = Data("POST /v1/test HTTP/1.1\r\nContent-Length: 5\r\n\r\n123".utf8)
        XCTAssertNil(HTTPParser.parse(incomplete))

        let complete = Data("POST /v1/test?a=b HTTP/1.1\r\nContent-Length: 5\r\n\r\n12345".utf8)
        let request = HTTPParser.parse(complete)
        XCTAssertEqual(request?.method, "POST")
        XCTAssertEqual(request?.path, "/v1/test")
        XCTAssertEqual(request?.queryItems, ["a": "b"])
        XCTAssertEqual(String(data: request?.body ?? Data(), encoding: .utf8), "12345")
    }

    func testParserSkipsEmptyQueryKeys() {
        let request = HTTPParser.parse(Data("GET /v1/windows?= HTTP/1.1\r\n\r\n".utf8))
        XCTAssertEqual(request?.queryItems, [:])
    }

    func testURLBuilderHandlesIPv6Loopback() {
        XCTAssertEqual(
            HTTPURLBuilder.make(host: "::1", port: 17421, path: "/v1/health")?.absoluteString,
            "http://[::1]:17421/v1/health"
        )
        XCTAssertEqual(
            HTTPURLBuilder.make(host: "127.0.0.1", port: 17421, path: "/v1/health")?.absoluteString,
            "http://127.0.0.1:17421/v1/health"
        )
    }

    func testParserRejectsUnsafeContentLengths() {
        for value in ["-1", String(Int.max), "1048577", "invalid"] {
            let data = Data("POST / HTTP/1.1\r\nContent-Length: \(value)\r\n\r\n".utf8)
            XCTAssertEqual(HTTPParser.rejectionReason(data), "Invalid Content-Length")
            XCTAssertNil(HTTPParser.parse(data))
        }

        let duplicate = Data(
            "POST / HTTP/1.1\r\nContent-Length: 0\r\nContent-Length: 1048577\r\n\r\n".utf8
        )
        XCTAssertEqual(HTTPParser.rejectionReason(duplicate), "Invalid Content-Length")
        XCTAssertNil(HTTPParser.parse(duplicate))
    }
}
