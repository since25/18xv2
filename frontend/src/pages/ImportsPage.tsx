import { useEffect, useState } from 'react'
import { Table, Button, Upload, message, Tag, Space, Typography, Card, Popconfirm } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import type { DeleteResponse, TreeImport, ImportListResponse } from '@/api/types'
import { formatDateTime } from '@/utils/format'

const { Title } = Typography

export default function ImportsPage() {
  const navigate = useNavigate()
  const [imports, setImports] = useState<TreeImport[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const data = await api.get<ImportListResponse>('/imports/data?limit=100')
      setImports(data.items ?? [])
    } catch (e: unknown) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load()
    }, 0)

    return () => window.clearTimeout(timer)
  }, [])

  const handleUpload = async (file: File) => {
    setUploading(true)
    const form = new FormData()
    form.append('file', file)
    try {
      await api.postForm('/imports/tree', form)
      message.success('目录树上传成功')
      load()
    } catch (e: unknown) {
      message.error((e as Error).message)
    } finally {
      setUploading(false)
    }
    return false
  }

  const deleteImport = async (importId: number) => {
    try {
      await api.delete<DeleteResponse>(`/imports/${importId}`)
      message.success(`已删除批次 #${importId}`)
      load()
    } catch (e: unknown) {
      message.error((e as Error).message)
    }
  }

  const columns: ColumnsType<TreeImport> = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    { title: '文件名', dataIndex: 'source_filename', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v: string) => <Tag color={v === 'done' ? 'green' : 'blue'}>{v}</Tag>,
    },
    { title: '备注', dataIndex: 'note', ellipsis: true },
    {
      title: '导入时间',
      dataIndex: 'imported_at',
      width: 180,
      render: (v: string) => formatDateTime(v),
    },
    {
      title: '操作',
      width: 260,
      render: (_value, record) => (
        <Space wrap size={4}>
          <Button size="small" onClick={() => navigate(`/extractor?import_id=${record.id}`)}>
            进入提取器
          </Button>
          <Button size="small" onClick={() => navigate(`/nodes?import_id=${record.id}`)}>
            查看内容
          </Button>
          <Button size="small" onClick={() => navigate(`/keywords?import_id=${record.id}`)}>
            去关键词台
          </Button>
          <Popconfirm title={`删除批次 #${record.id}？`} onConfirm={() => deleteImport(record.id)}>
            <Button size="small" danger>删除批次</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16 }} align="center">
        <Title level={4} style={{ margin: 0 }}>导入批次</Title>
        <Upload beforeUpload={handleUpload} showUploadList={false} accept=".txt,.json">
          <Button icon={<UploadOutlined />} loading={uploading}>上传目录树</Button>
        </Upload>
        <Button onClick={() => navigate('/nodes')}>查看目录内容</Button>
        <Button onClick={() => navigate('/extractor')}>打开提取器</Button>
        <Button onClick={() => navigate('/keywords')}>打开关键词台</Button>
        <Button onClick={load} loading={loading}>刷新</Button>
      </Space>
      <Card>
        <Table
          rowKey="id"
          dataSource={imports}
          columns={columns}
          loading={loading}
          size="small"
          pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
        />
      </Card>
    </div>
  )
}
