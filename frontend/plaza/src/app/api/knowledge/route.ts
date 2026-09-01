import { readFile } from 'node:fs/promises'
import path from 'node:path'

export const dynamic = 'force-dynamic'

type ReportFile = {
  chunks?: number
  chars?: number
}

type KnowledgeReport = {
  backend?: string
  files?: Record<string, ReportFile>
}

export async function GET() {
  try {
    const configuredPath = process.env.VECTOR_STORE_REPORT || '../../vector_store/base/download_report.json'

    const reportPath = path.isAbsolute(configuredPath)
      ? configuredPath
      : path.resolve(process.cwd(), configuredPath)

    const report = JSON.parse(await readFile(reportPath, 'utf8')) as KnowledgeReport

    const documents = Object.entries(report.files || {})
      .map(([source, file]) => ({
        source,
        category: source.includes('/') ? source.split('/')[0] : '其他资料',
        chunks: file.chunks || 0
      }))
      .sort((a, b) => a.source.localeCompare(b.source, 'zh-CN'))

    const categories = Object.values(
      documents.reduce<Record<string, { name: string; documents: number; chunks: number }>>((result, document) => {
        result[document.category] ||= { name: document.category, documents: 0, chunks: 0 }
        result[document.category].documents += 1
        result[document.category].chunks += document.chunks

        return result
      }, {})
    )

    return Response.json({
      status: 'ready',
      documentCount: documents.length,
      chunkCount: documents.reduce((total, document) => total + document.chunks, 0),
      dimension: 0,
      provider: report.backend || 'iflytek_chatdoc',
      categories,
      documents
    })
  } catch (error) {
    return Response.json(
      {
        status: 'unavailable',
        message: '暂时无法读取本地知识库清单。',
        detail: error instanceof Error ? error.message : 'unknown error'
      },
      { status: 503 }
    )
  }
}
