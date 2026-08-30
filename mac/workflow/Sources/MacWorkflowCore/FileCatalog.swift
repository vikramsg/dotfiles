import Foundation

public struct FileCatalogItem: Equatable {
    public let url: URL
    public let modificationDate: Date

    public init(url: URL, modificationDate: Date) {
        self.url = url
        self.modificationDate = modificationDate
    }
}

public enum FileCatalog {
    public static func sortedItems(
        candidates: [ScreenshotCandidate],
        supportedExtensions: Set<String>
    ) -> [FileCatalogItem] {
        candidates
            .filter { $0.regularFile && supportedExtensions.contains($0.url.pathExtension.lowercased()) }
            .map { FileCatalogItem(url: $0.url, modificationDate: $0.modificationDate) }
            .sorted {
                if $0.modificationDate == $1.modificationDate {
                    return $0.url.path > $1.url.path
                }
                return $0.modificationDate > $1.modificationDate
            }
    }

    public static func items(in directory: URL, supportedExtensions: Set<String>) -> [FileCatalogItem] {
        let keys: Set<URLResourceKey> = [.isRegularFileKey, .contentModificationDateKey]
        guard let urls = try? FileManager.default.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: Array(keys),
            options: [.skipsHiddenFiles]
        ) else { return [] }
        let candidates = urls.map { url -> ScreenshotCandidate in
            let values = try? url.resourceValues(forKeys: keys)
            return ScreenshotCandidate(
                url: url,
                modificationDate: values?.contentModificationDate ?? .distantPast,
                regularFile: values?.isRegularFile == true
            )
        }
        return sortedItems(candidates: candidates, supportedExtensions: supportedExtensions)
    }
}
