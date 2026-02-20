import {
	IDataObject,
	IExecuteFunctions,
	IHttpRequestOptions,
	ILoadOptionsFunctions,
	NodeOperationError,
	sleep,
} from 'n8n-workflow';

/**
 * Make an authenticated request to the OpenOutreach REST API.
 *
 * Uses this.helpers.httpRequest() — the current n8n-workflow API (not the
 * deprecated this.helpers.request()). Credentials are read from the
 * 'openOutreachApi' credential vault (baseUrl + apiKey fields).
 *
 * @param method   HTTP method
 * @param path     API path beginning with '/' (e.g. '/jobs/42/')
 * @param body     Optional JSON request body
 * @param qs       Optional query-string parameters
 */
export async function openOutreachRequest(
	this: IExecuteFunctions | ILoadOptionsFunctions,
	method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
	path: string,
	body?: IDataObject,
	qs?: IDataObject,
): Promise<IDataObject | IDataObject[]> {
	const credentials = await this.getCredentials('openOutreachApi');
	const baseUrl = (credentials.baseUrl as string).replace(/\/$/, '');

	const options: IHttpRequestOptions = {
		method,
		url: `${baseUrl}/api/v1${path}`,
		headers: {
			'Content-Type': 'application/json',
		},
		body,
		qs,
		json: true,
	};

	return this.helpers.httpRequestWithAuthentication.call(this, 'openOutreachApi', options);
}

/**
 * Poll GET /jobs/{jobId}/ every intervalMs until status is 'completed' or
 * 'failed', or until timeoutMs elapses.
 *
 * Throws NodeOperationError if the job fails or the poll times out.
 * Uses a do-while loop to guarantee at least one status check.
 *
 * @param ctx        IExecuteFunctions context (provides credentials + helpers)
 * @param jobId      The job_id string returned by the lane trigger endpoint
 * @param timeoutMs  Maximum wait time in milliseconds (default: 300 000 = 5 min)
 * @param intervalMs Poll interval in milliseconds (default: 5 000 = 5 s)
 * @returns          The final job object (status 'completed')
 */
export async function pollJobUntilDone(
	ctx: IExecuteFunctions,
	jobId: string,
	timeoutMs = 300_000,
	intervalMs = 5_000,
): Promise<IDataObject> {
	const numericId = parseInt(jobId, 10);
	if (isNaN(numericId)) {
		throw new NodeOperationError(ctx.getNode(), `Invalid job ID: "${jobId}" is not a valid integer`);
	}

	const deadline = Date.now() + timeoutMs;

	let pending = true;
	while (pending) {
		const job = (await openOutreachRequest.call(ctx, 'GET', `/jobs/${numericId}/`)) as IDataObject;
		const status = job.status as string;

		if (status === 'failed') {
			throw new NodeOperationError(ctx.getNode(), `Job ${jobId} failed: ${String(job.result ?? 'no detail')}`);
		}
		if (status === 'completed') {
			return job;
		}
		if (Date.now() >= deadline) {
			pending = false;
		} else {
			await sleep(intervalMs);
		}
	}

	throw new NodeOperationError(ctx.getNode(), `Job ${jobId} timed out after ${timeoutMs / 1000}s`);
}
