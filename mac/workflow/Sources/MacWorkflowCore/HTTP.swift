import Foundation

public struct HTTPRequest: Equatable {
    public let method: String
    public let target: String
    public let headers: [String: String]
    public let body: Data

    public var path: String {
        String(target.split(separator: "?", maxSplits: 1).first ?? "")
    }

    public var queryItems: [String: String] {
        guard let separator = target.firstIndex(of: "?") else { return [:] }
        return target[target.index(after: separator)...]
            .split(separator: "&", omittingEmptySubsequences: true)
            .reduce(into: [:]) { result, pair in
                let parts = pair.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false).map(String.init)
                guard let rawKey = parts.first, !rawKey.isEmpty else { return }
                let key = rawKey.removingPercentEncoding ?? rawKey
                let value = parts.count == 2 ? (parts[1].removingPercentEncoding ?? parts[1]) : ""
                result[key] = value
            }
    }
}

public enum HTTPURLBuilder {
    public static func make(host: String, port: UInt16, path: String) -> URL? {
        let formattedHost = host.contains(":") ? "[\(host)]" : host
        return URL(string: "http://\(formattedHost):\(port)\(path)")
    }
}

public enum HTTPParser {
    public static let maximumBodySize = 1_048_576

    public static func rejectionReason(_ data: Data, maximumBodySize: Int = maximumBodySize) -> String? {
        guard let marker = "\r\n\r\n".data(using: .utf8),
              let headerRange = data.range(of: marker),
              let headerText = String(data: data[..<headerRange.lowerBound], encoding: .utf8)
        else { return nil }

        let lines = headerText.components(separatedBy: "\r\n")
        let contentLengths = lines.dropFirst()
            .filter { $0.lowercased().hasPrefix("content-length:") }
        guard contentLengths.count <= 1 else { return "Invalid Content-Length" }
        guard let contentLength = contentLengths.first else { return nil }
        let rawLength = contentLength
            .split(separator: ":", maxSplits: 1)
            .last?
            .trimmingCharacters(in: .whitespaces) ?? ""
        guard !rawLength.isEmpty,
              rawLength.allSatisfy(\.isNumber),
              let length = Int(rawLength),
              length <= maximumBodySize
        else { return "Invalid Content-Length" }
        return nil
    }

    public static func parse(_ data: Data, maximumBodySize: Int = maximumBodySize) -> HTTPRequest? {
        guard rejectionReason(data, maximumBodySize: maximumBodySize) == nil,
              let marker = "\r\n\r\n".data(using: .utf8),
              let headerRange = data.range(of: marker),
              let headerText = String(data: data[..<headerRange.lowerBound], encoding: .utf8)
        else { return nil }

        let lines = headerText.components(separatedBy: "\r\n")
        let requestLine = lines[0].split(separator: " ")
        guard requestLine.count >= 2 else { return nil }

        var headers: [String: String] = [:]
        for line in lines.dropFirst() {
            guard let separator = line.firstIndex(of: ":") else { continue }
            headers[String(line[..<separator]).lowercased()] = String(line[line.index(after: separator)...])
                .trimmingCharacters(in: .whitespaces)
        }

        let bodyStart = headerRange.upperBound
        let length = Int(headers["content-length"] ?? "0") ?? 0
        let (bodyEnd, overflow) = bodyStart.addingReportingOverflow(length)
        guard !overflow, length >= 0, length <= maximumBodySize, data.count >= bodyEnd else { return nil }
        return HTTPRequest(
            method: String(requestLine[0]),
            target: String(requestLine[1]),
            headers: headers,
            body: data.subdata(in: bodyStart..<bodyEnd)
        )
    }
}
