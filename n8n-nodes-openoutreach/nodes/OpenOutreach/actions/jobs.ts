import { IDataObject, IExecuteFunctions, INodeExecutionData, INodeProperties } from 'n8n-workflow';
import { openOutreachRequest } from '../helpers';

export const jobsOperations: INodeProperties[] = [
	{
		displayName: 'Operation',
		name: 'operation',
		type: 'options',
		noDataExpression: true,
		displayOptions: { show: { resource: ['jobs'] } },
		options: [
			{ name: 'Get', value: 'get', description: 'Get a single job by ID', action: 'Get a job' },
			{ name: 'Get Many', value: 'getMany', description: 'List jobs with optional status filter', action: 'Get many jobs' },
		],
		default: 'get',
	},
];

export const jobsFields: INodeProperties[] = [
	{
		displayName: 'Job ID',
		name: 'jobId',
		type: 'string',
		required: true,
		displayOptions: { show: { resource: ['jobs'], operation: ['get'] } },
		default: '',
		description: 'String ID of the job to retrieve',
	},
	{
		displayName: 'Status Filter',
		name: 'status',
		type: 'options',
		displayOptions: { show: { resource: ['jobs'], operation: ['getMany'] } },
		options: [
			{ name: 'All', value: '' },
			{ name: 'Completed', value: 'completed' },
			{ name: 'Failed', value: 'failed' },
			{ name: 'Pending', value: 'pending' },
			{ name: 'Running', value: 'running' },
		],
		default: '',
		description: 'Filter jobs by status (leave blank for all)',
	},
];

export async function executeJobs(
	this: IExecuteFunctions,
	i: number,
): Promise<INodeExecutionData[]> {
	const operation = this.getNodeParameter('operation', i) as string;

	if (operation === 'get') {
		const jobId = this.getNodeParameter('jobId', i) as string;
		const result = (await openOutreachRequest.call(this, 'GET', `/jobs/${jobId}/`)) as IDataObject;
		return [{ json: result }];
	}

	// getMany — handle both a plain array and a paginated { results: [...] } shape
	const status = this.getNodeParameter('status', i, '') as string;
	const qs: IDataObject = {};
	if (status) qs.status = status;
	const response = await openOutreachRequest.call(this, 'GET', '/jobs/', undefined, qs);

	let items: IDataObject[];
	if (Array.isArray(response)) {
		items = response as IDataObject[];
	} else {
		const paginated = response as IDataObject;
		items = (paginated.results as IDataObject[]) ?? [paginated];
	}

	return items.map((r) => ({ json: r }));
}
